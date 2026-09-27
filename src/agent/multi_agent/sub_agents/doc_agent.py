import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.agent.language import message, response_language
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.agent.nodes import GRADE_UNAVAILABLE, is_grade_passed
from src.agent.prompts import (
    build_grader_messages,
    build_rag_messages,
    build_refine_messages,
    build_rewrite_messages,
)
from src.rag.rag_engine import RAGEngine
from src.core.logger import get_logger

logger = get_logger("MultiAgent.DocAgent")


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
        """Execute two-stage dense retrieval and grounded answer generation."""
        start_time = time.time()
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        language = response_language(question, chat_history)

        logger.info(f"[{self.name}] Executing document search for: '{question}'")

        # 1. Query reformulation for multi-turn coherence
        search_query = question
        if chat_history and len(question.split()) > 3:
            try:
                rewrite_messages = build_rewrite_messages(question, chat_history)
                rewrite_resp = self.chat_model.invoke(rewrite_messages)
                rewritten = rewrite_resp.content.strip()
                if rewritten and len(rewritten) < 500:
                    search_query = rewritten
                    logger.info(f"[{self.name}] Query rewritten to: '{search_query}'")
            except Exception as e:
                logger.warning(f"[{self.name}] Query rewrite failed, using original: {e}")

        # 2. Retrieve documents via BGE-M3 + Cross-Encoder Reranker
        engine = self._get_engine()
        try:
            search_result = engine.search(search_query, allowed_groups=self.search_groups(state))
        except Exception as e:
            logger.error(f"[{self.name}] Retrieval error: {e}")
            search_result = {"context": "", "sources": []}
        context = search_result.get("context", "").strip()
        sources = search_result.get("sources", [])

        # 3. Handle zero-context fallback
        if not context:
            duration_ms = int((time.time() - start_time) * 1000)
            trace_entry = {
                "agent": self.name,
                "display_name": self.display_name,
                "action": "document_retrieval",
                "sources_count": 0,
                "duration_ms": duration_ms,
                "status": "no_context",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "final_answer": message("no_context", language),
                "sources": [],
                "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
            }

        # 4. Generate grounded response with chat history context
        generation_failed = False
        try:
            messages = build_rag_messages(context, question, chat_history, language=language)
            response = self.chat_model.invoke(messages)
            answer = response.content.strip()
        except Exception as e:
            logger.error(f"[{self.name}] LLM generation error: {e}")
            answer = message("fallback", language)
            generation_failed = True

        # 5. Self-RAG hallucination guard: grade -> (refine -> re-grade) -> fallback
        is_refined = False
        grade = ""
        if not generation_failed:
            grade = self._grade(context, question, answer)
            if not is_grade_passed(grade):
                logger.info(f"[{self.name}] Answer not grounded ('{grade}'), refining...")
                answer = self._refine(context, question, answer, language)
                is_refined = True
                grade = self._grade(context, question, answer)
                if not is_grade_passed(grade):
                    logger.warning(f"[{self.name}] Refined answer still unverified, using safe fallback.")
                    answer = message("fallback", language)

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "retrieval_and_generation",
            "search_query": search_query,
            "sources_count": len(sources),
            "hallucination_grade": grade,
            "is_refined": is_refined,
            "duration_ms": duration_ms,
            "status": "success" if is_grade_passed(grade) else "unverified",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "final_answer": answer,
            "sources": sources,
            "hallucination_grade": grade,
            "is_refined": is_refined,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }

    def _grade(self, context: str, question: str, answer: str) -> str:
        """Ask the LLM whether the answer is supported by the context; fails closed on errors."""
        try:
            response = self.grader_model.invoke(build_grader_messages(context, question, answer))
            return response.content.strip()
        except Exception as e:
            logger.error(f"[{self.name}] Grading error, treating answer as unverified: {e}")
            return GRADE_UNAVAILABLE

    def _refine(self, context: str, question: str, draft_answer: str, language: str) -> str:
        """Prune claims from the draft that the context does not support."""
        try:
            response = self.chat_model.invoke(build_refine_messages(context, question, draft_answer, language))
            return response.content.strip() or draft_answer
        except Exception as e:
            logger.error(f"[{self.name}] Refinement error, keeping draft: {e}")
            return draft_answer
