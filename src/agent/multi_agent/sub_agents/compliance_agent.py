import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.language import language_instruction, message, response_language
from src.agent.llm import for_task, json_mode
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.agent.prompts import ORGANIZATION, step_context_text, with_thinking_guide
from src.auth.profile import profile_note
from src.agent.verification import UNVERIFIED, VERIFIED, check_answer
from src.core import config
from src.rag.evidence import attach_evidence
from src.rag.rag_engine import RAGEngine
from src.core.logger import get_logger

logger = get_logger("MultiAgent.ComplianceAgent")

COMPLIANCE_SYSTEM_PROMPT = """You are a senior compliance and legal auditor of {organization}.
Your mission is to objectively audit the user's stated scenario, action, request, or contractual clause against the organization's official rules, regulations, and policies.

Below are the relevant rules, regulations, policies, and guidelines retrieved from the organization's knowledge base:
--------------------
{context}
--------------------

AUDIT AND REPORTING STANDARDS:
You MUST produce your response in the following structured corporate audit format:

### {heading_verdict}
Explicitly select exactly one of the following four categories:
- **[COMPLIANT]**: The action is fully compliant with the rules above.
- **[WARNING / CONDITIONALLY COMPLIANT]**: Permissible only if specific prerequisites, approvals, or conditions are satisfied.
- **[VIOLATION / PROHIBITED]**: The action violates a rule above (e.g. a regulation, a code of conduct, information security or data protection such as GDPR/KVKK) and cannot be permitted.
- **[UNDETERMINED]**: None of the policies above address this scenario. Never infer a verdict from general knowledge.

### {heading_references}
Specify the document name and the relevant article, section, or policy code from the context above (e.g. "Madde 53", "SEC-POL-04 Section 4.1").

### {heading_risk}
Analyze the legal, disciplinary, administrative, security, or operational risks of the action for the person and the organization.

### {heading_actions}
Approvals required by the rules above and the proper procedure steps. Name approving roles or units only as they appear in the context; otherwise refer to "the responsible unit".

Base the verdict only on the rules above. If none of them address the scenario, choose [UNDETERMINED], state that no written rule was identified, and recommend consulting the responsible unit (for example legal counsel or the data protection officer).

LANGUAGE: {language_rule} Use the section headings exactly as written above, and copy the verdict label exactly as listed (e.g. [VIOLATION / PROHIBITED]).
"""

# A scenario often involves several rules ("70% attendance, may they sit the exam?": the attendance rule and who
# may sit the exam); searching with the scenario alone finds the passages that resemble its wording
SEARCH_QUERIES_PROMPT = """You prepare the document search for a compliance audit.
Name the rules that must be looked up to judge the scenario: one short search query per rule, condition, limit, or deadline it involves (at most {count}), worded as a regulation would state the rule, in the language of the scenario. Do not judge the scenario.
Example: "Stajını tamamlamayan bir öğrencinin mezun edilmesi uygun mu?" -> {{"queries": ["staj zorunluluğu", "mezuniyet koşulları"]}}
Reply with JSON only: {{"queries": ["..."]}}"""

# The verdict label of a report, e.g. "[VIOLATION / PROHIBITED]"
_VERDICT_LABEL = re.compile(r"\[(COMPLIANT|WARNING[^\]]*|VIOLATION[^\]]*|UNDETERMINED)\]")

# Section headings per response language. Models copy template headings verbatim, so the template itself is
# localized instead of asking the model to translate. Verdict labels stay English (machine-readable).
REPORT_HEADINGS = {
    "en": {
        "heading_verdict": "📌 1. Audit Verdict",
        "heading_references": "📑 2. Underlying Rules & Article References",
        "heading_risk": "🔍 3. Risk & Impact Assessment",
        "heading_actions": "💡 4. Required Approvals & Action Plan",
    },
    "tr": {
        "heading_verdict": "📌 1. Denetim Kararı",
        "heading_references": "📑 2. Dayanak Mevzuat ve Madde Referansları",
        "heading_risk": "🔍 3. Risk ve Etki Değerlendirmesi",
        "heading_actions": "💡 4. Gerekli Onaylar ve Eylem Planı",
    },
}


@register_agent
class ComplianceAuditorAgent(BaseSubAgent):
    """Specialist sub-agent for auditing enterprise actions against compliance policies and producing structured verdicts."""

    name: str = "compliance_agent"
    display_name: str = "Compliance Auditor"
    # Kept narrow on purpose: a broad "policies / HR rules" wording pulls plain policy questions away from doc_agent
    description: str = (
        "Gives a formal verdict [COMPLIANT / WARNING / VIOLATION] on a specific action or scenario the user "
        "describes, by checking it against the organization's rules, regulations, and policies (incl. KVKK/GDPR)."
    )

    def __init__(self, chat_model=None, rag_engine: Optional[RAGEngine] = None, grader_model=None):
        super().__init__(chat_model=chat_model)
        self._rag_engine = rag_engine
        self._grader_model = grader_model

    @property
    def grader_model(self):
        """Model that checks the verdict against the rules (OLLAMA_GRADER_MODEL); defaults to chat_model."""
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
        """Audit user scenario against enterprise policies and output structured compliance report."""
        start_time = time.time()
        question = state.get("question", "").strip()
        language = response_language(question, state.get("chat_history", []))

        logger.info(f"[{self.name}] Auditing compliance scenario: '{question}'")

        # 1. Search relevant compliance policies and regulations
        engine = self._get_engine()
        scope = self.search_groups(state)
        search_result = engine.search(question, allowed_groups=scope)
        context = search_result.get("context", "").strip()
        sources = search_result.get("sources", [])
        # Rules exist on the topic: also search the rules the scenario involves one by one. A scenario no
        # document covers is still answered below without calling the model.
        queries = self._search_queries(question) if context else []
        if queries:
            search_result = engine.search_many(queries, allowed_groups=scope, initial=sources)
            context = search_result.get("context", "").strip()
            sources = search_result.get("sources", [])

        if not context:
            duration_ms = int((time.time() - start_time) * 1000)
            answer = message("compliance_undetermined", language)
            return {
                "final_answer": answer,
                "sources": [],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": self.name,
                        "display_name": self.display_name,
                        "action": "compliance_audit",
                        "verdict": "NO_POLICY_FOUND",
                        "sources_count": 0,
                        "duration_ms": duration_ms,
                        "status": "warning",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # 2. Generate structured audit report
        prompt = COMPLIANCE_SYSTEM_PROMPT.format(
            organization=ORGANIZATION,
            context=context,
            language_rule=language_instruction(language),
            **REPORT_HEADINGS.get(language, REPORT_HEADINGS["en"]),
        )
        user_note = profile_note(state.get("user"))
        if user_note:
            prompt = f"{prompt}\n{user_note}"
        earlier_steps = step_context_text(state.get("step_context"))
        status = "success"
        scenario = f"{earlier_steps}Scenario / Request to Audit: {question}"
        verification = None
        # For the trace: the first verdict and why a verdict was sent back or dropped
        first_verdict, objections = "", []
        try:
            audit_report = self._report(prompt, scenario)
            label = _VERDICT_LABEL.search(audit_report)
            first_verdict = label.group(1) if label else ""
            # The verdict and the rules it cites must be in the retrieved rules: a wrong VIOLATION is costly.
            # One revision with the objection, then an undetermined verdict instead of an unsupported one.
            self.report_progress("verifying")
            check = check_answer(
                self.grader_model, context, question, _verdict_part(audit_report), sources, "", False, self.name
            )
            if not check.passed:
                logger.warning(f"[{self.name}] Verdict not supported by the rules: {check.objection}")
                objections.append(check.objection or check.grade)
                revision = f"{scenario}\n\nAn auditor rejected the previous verdict: {check.objection}"
                audit_report = self._report(prompt, revision)
                check = check_answer(
                    self.grader_model, context, question, _verdict_part(audit_report), sources, "", False, self.name
                )
            if check.passed:
                sources = attach_evidence(sources, check.quotes)
                verification = {"level": VERIFIED, "issues": check.warnings}
            else:
                objections.append(check.objection or check.grade)
                audit_report = message("compliance_unsupported", language)
                verification = {"level": UNVERIFIED, "issues": []}
                status = "unverified"
        except Exception as e:
            logger.error(f"[{self.name}] Compliance audit LLM error: {e}")
            audit_report = message("compliance_error", language)
            status = "error"

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "compliance_audit",
            "sources_count": len(sources),
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in (("search_queries", queries), ("first_verdict", first_verdict), ("objections", objections)):
            if value:
                trace_entry[key] = value

        result = {
            "final_answer": audit_report,
            "sources": sources,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
        if verification:
            result["verification"] = verification
        return result

    def _search_queries(self, question: str) -> List[str]:
        """Search queries for the rules the scenario involves, written by the model; [] to search with the
        scenario only (turned off, or the model's reply cannot be read)."""
        count = config.COMPLIANCE_SEARCH_QUERIES
        if count <= 0:
            return []
        try:
            reply = json_mode(for_task(self.chat_model, "queries")).invoke(
                [SystemMessage(content=SEARCH_QUERIES_PROMPT.format(count=count)), HumanMessage(content=question)]
            )
            data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.content.strip()))
            queries = [str(q).strip() for q in data.get("queries") or [] if isinstance(q, str) and q.strip()]
            return [q for q in queries if len(q) <= 200][:count]
        except Exception as e:
            logger.info(f"[{self.name}] No search queries from the model, searching with the scenario: {e}")
            return []

    def _report(self, prompt: str, scenario: str) -> str:
        model = for_task(self.chat_model, "compliance")
        messages = [SystemMessage(content=prompt), HumanMessage(content=scenario)]
        return model.invoke(with_thinking_guide(messages, model, "compliance")).content.strip()


# The report's third heading ("### 🔍 3. ...") starts the risk assessment, which is analysis rather than a rule
_RISK_HEADING = re.compile(r"(?m)^#{1,4}\s*\S*\s*3\.")


_HEADING_LINE = re.compile(r"(?m)^#{1,4}\s.*$")


def _verdict_part(report: str) -> str:
    """The verdict and the cited rules of a report: the part that must be stated in the retrieved rules.

    Headings are left out: their numbers ("1. Denetim Kararı") are no facts for the number check.
    """
    match = _RISK_HEADING.search(report)
    part = report[: match.start()] if match else report
    return _HEADING_LINE.sub("", part).strip()
