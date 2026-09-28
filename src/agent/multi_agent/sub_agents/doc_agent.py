import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.agent.language import message, response_language
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.agent.answer_cache import answer_cache
from src.agent.grading import grade_objection, is_grade_passed, quote_in_context
from src.agent.multi_agent.tools import ToolRun, build_tools, run_with_tools
from src.agent.prompts import build_rag_messages, build_rewrite_messages, split_evidence
from src.agent.self_rag import grade_answer, grade_answer_with_quotes, refine_answer
from src.core import config
from src.rag.evidence import attach_evidence
from src.rag.rag_engine import RAGEngine
from src.core.logger import get_logger

logger = get_logger("MultiAgent.DocAgent")

# Words that point back to the conversation ("Peki bunun süresi?", "What about that one?")
_REFERENCE_WORDS = frozenset(
    """
    bu bunu bunun buna bunda bunlar bunları şu şunu onu onun ona onlar aynı peki ya öyleyse
    it this that these those they them same what about
    """.split()
)


def needs_rewrite(question: str, chat_history) -> bool:
    """Whether a question needs the conversation to be searchable: short follow-ups ("Peki doktora için?")
    and questions that refer back ("Bunun süresi ne kadar?"). Long standalone questions are searched as asked."""
    if not chat_history:
        return False
    words = re.findall(r"\w+", question.replace("İ", "i").casefold())
    return len(words) <= 6 or any(word in _REFERENCE_WORDS for word in words)


@register_agent
class DocumentRagAgent(BaseSubAgent):
    """Specialist sub-agent for dense vector search and factual grounding over enterprise documents."""

    name: str = "doc_agent"
    display_name: str = "Document & Regulation Specialist"
    # Routing depends mostly on this text: name the question types, not the retrieval technique
    description: str = (
        "Answers questions about what the organization's documents say: laws, regulations, policies, "
        "procedures, guidelines, handbooks; limits, counts, deadlines, durations, penalties, required approvals "
        "and steps (PDF, DOCX, TXT)."
    )

    def __init__(self, chat_model=None, rag_engine: Optional[RAGEngine] = None, grader_model=None):
        super().__init__(chat_model=chat_model)
        self._rag_engine = rag_engine
        self._grader_model = grader_model

    @property
    def grader_model(self):
        """Model that checks answers against the documents (OLLAMA_GRADER_MODEL); defaults to chat_model."""
        return self._grader_model or self.chat_model

    @grader_model.setter
    def grader_model(self, value):
        self._grader_model = value

    def _get_engine(self) -> RAGEngine:
        if self._rag_engine is None:
            from src.api.state import get_rag_engine

            self._rag_engine = get_rag_engine()
        return self._rag_engine

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve the relevant passages, answer from them, check the answer, and attach its evidence."""
        start_time = time.time()
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        language = response_language(question, chat_history)
        engine = self._get_engine()
        scope = self.search_groups(state)

        logger.info(f"[{self.name}] Executing document search for: '{question}'")

        # 1. First questions of a conversation: reuse a verified answer to the same question and documents
        cache_key = None
        if not chat_history:
            cache_key = answer_cache.key(question, scope, getattr(engine, "index_version", 0))
            cached = answer_cache.get(cache_key)
            if cached:
                logger.info(f"[{self.name}] Answer reused from the cache.")
                trace_entry = self._trace_entry("cache_hit", question, len(cached["sources"]), cached, start_time)
                return {**cached, "agent_trace": list(state.get("agent_trace", [])) + [trace_entry]}

        # 2. Follow-up questions ("Peki doktora için?") become standalone search queries
        search_query = question
        if needs_rewrite(question, chat_history):
            try:
                rewritten = self.chat_model.invoke(build_rewrite_messages(question, chat_history)).content.strip()
                if rewritten and len(rewritten) < 500:
                    search_query = rewritten
                    logger.info(f"[{self.name}] Query rewritten to: '{search_query}'")
            except Exception as e:
                logger.warning(f"[{self.name}] Query rewrite failed, using original: {e}")

        # 3. Retrieve documents via BGE-M3 + Cross-Encoder Reranker
        self.report_progress("searching")
        try:
            search_result = engine.search(search_query, allowed_groups=scope)
        except Exception as e:
            logger.error(f"[{self.name}] Retrieval error: {e}")
            search_result = {"context": "", "sources": []}
        context = search_result.get("context", "").strip()
        sources = search_result.get("sources", [])

        if not context:
            output = {"final_answer": message("no_context", language), "sources": []}
            trace_entry = self._trace_entry("document_retrieval", search_query, 0, {"status": "no_context"}, start_time)
            return {**output, "agent_trace": list(state.get("agent_trace", [])) + [trace_entry]}

        # 4. Generate the answer (optionally copying its evidence first, optionally with calculator and dates)
        self.report_progress("writing")
        run = ToolRun()
        messages = build_rag_messages(
            context, question, chat_history, language=language, evidence_first=config.ANSWER_EVIDENCE_FIRST
        )
        tools = build_tools(["calculator", "dates"], run, state) if config.DOC_AGENT_TOOLS else []
        answer, tools_called, status = run_with_tools(self.chat_model, messages, tools, self.name)
        generation_failed = status != "success" or not answer
        answer_quotes = []
        if not generation_failed and config.ANSWER_EVIDENCE_FIRST:
            answer_quotes, answer = split_evidence(answer)
            if not answer:
                # Only "EVIDENCE: none": the context does not answer the question
                answer = message("no_context", language)
        if generation_failed:
            answer = message("fallback", language)
        # Computed values (a deadline, a sum) are context for the check like the quoted rules
        check_context = "\n\n".join(part for part in (context, run.context()) if part)

        # 5. Self-RAG hallucination guard: grade -> (refine -> re-grade) -> fallback
        is_refined, grade, quotes = False, "", []
        if not generation_failed:
            self.report_progress("verifying")
            grade, quotes = self._grade_with_quotes(check_context, question, answer)
            if not is_grade_passed(grade):
                logger.info(f"[{self.name}] Answer not grounded ('{grade}'), refining...")
                self.report_progress("refining")
                answer = self._refine(check_context, question, answer, language, objection=grade_objection(grade))
                is_refined = True
                grade, quotes = self._grade_with_quotes(check_context, question, answer)
                if not is_grade_passed(grade):
                    logger.warning(f"[{self.name}] Refined answer still unverified, using safe fallback.")
                    answer = message("fallback", language)

        # 6. The sentences the answer relies on, shown with the answer ("Madde 30/2")
        if is_grade_passed(grade):
            evidence = quotes or [q for q in answer_quotes if quote_in_context(q, context)]
            sources = attach_evidence(sources, evidence)

        output = {"final_answer": answer, "sources": sources, "hallucination_grade": grade, "is_refined": is_refined}
        details = {"hallucination_grade": grade, "is_refined": is_refined, "tools_called": tools_called}
        details["status"] = "success" if is_grade_passed(grade) else "unverified"
        trace_entry = self._trace_entry("retrieval_and_generation", search_query, len(sources), details, start_time)
        if cache_key is not None and is_grade_passed(grade):
            answer_cache.put(cache_key, output)
        return {**output, "agent_trace": list(state.get("agent_trace", [])) + [trace_entry]}

    def _trace_entry(self, action: str, search_query: str, sources_count: int, details: dict, start_time: float):
        entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": action,
            "search_query": search_query,
            "sources_count": sources_count,
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": details.get("status", "success"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for key in ("hallucination_grade", "is_refined", "tools_called"):
            if key in details and details[key] not in (None, []):
                entry[key] = details[key]
        return entry

    def _grade_with_quotes(self, context: str, question: str, answer: str) -> tuple:
        return grade_answer_with_quotes(self.grader_model, context, question, answer, agent_name=self.name)

    def _grade(self, context: str, question: str, answer: str) -> str:
        """Ask the grading model whether the answer is supported by the context (see src/agent/self_rag.py)."""
        return grade_answer(self.grader_model, context, question, answer, agent_name=self.name)

    def _refine(self, context: str, question: str, draft_answer: str, language: str, objection: str = "") -> str:
        """Prune claims from the draft that the context does not support (the grader's objection first)."""
        return refine_answer(self.chat_model, context, question, draft_answer, language, objection, self.name)
