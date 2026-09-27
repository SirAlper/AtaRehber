import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.language import language_instruction, message, response_language
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.rag.rag_engine import RAGEngine
from src.core.logger import get_logger

logger = get_logger("MultiAgent.ComplianceAgent")

COMPLIANCE_SYSTEM_PROMPT = """You are a senior Corporate Compliance, Legal, and Information Security Auditor (Chief Compliance & Information Security Officer).
Your mission is to objectively audit the user's stated scenario, action, request, or contractual clause against official enterprise policies and regulations.

Below are the relevant enterprise policies, guidelines, and rules retrieved from the corporate knowledge base:
--------------------
{context}
--------------------

AUDIT AND REPORTING STANDARDS:
You MUST produce your response in the following structured corporate audit format:

### {heading_verdict}
Explicitly select exactly one of the following four categories:
- **[COMPLIANT]**: The request is fully compliant with company policies.
- **[WARNING / CONDITIONALLY COMPLIANT]**: Permissible only if specific security or administrative prerequisites/approvals are satisfied.
- **[VIOLATION / PROHIBITED]**: The request violates enterprise information security, data privacy (GDPR/KVKK), or code of conduct rules, and cannot be permitted.
- **[UNDETERMINED]**: None of the policies above address this scenario. Never infer a verdict from general knowledge.

### {heading_references}
Specify the document name, policy code, and relevant sections from the context above (e.g., SEC-POL-04 Section 4.1).

### {heading_risk}
Analyze the security, legal, administrative, or operational risks the action poses to the enterprise.

### {heading_actions}
Required administrative approvals (CISO, DPO, HR, Legal) or proper procedure steps to execute this request safely.

Base the verdict only on the policies above. If none of them address the scenario, choose [UNDETERMINED], state that no written policy was identified, and recommend consulting the Legal or Information Security team.

LANGUAGE: {language_rule} Use the section headings exactly as written above, and copy the verdict label exactly as listed (e.g. [VIOLATION / PROHIBITED]).
"""

# Section headings per response language. Models copy template headings verbatim, so the template itself is
# localized instead of asking the model to translate. Verdict labels stay English (machine-readable).
REPORT_HEADINGS = {
    "en": {
        "heading_verdict": "📌 1. Audit Verdict",
        "heading_references": "📑 2. Underlying Policy & Clause References",
        "heading_risk": "🔍 3. Risk & Impact Assessment",
        "heading_actions": "💡 4. Mandatory Approvals & Action Plan",
    },
    "tr": {
        "heading_verdict": "📌 1. Denetim Kararı",
        "heading_references": "📑 2. Dayanak Politika ve Madde Referansları",
        "heading_risk": "🔍 3. Risk ve Etki Değerlendirmesi",
        "heading_actions": "💡 4. Gerekli Onaylar ve Eylem Planı",
    },
}


@register_agent
class ComplianceAuditorAgent(BaseSubAgent):
    """Specialist sub-agent for auditing enterprise actions against compliance policies and producing structured verdicts."""

    name: str = "compliance_agent"
    display_name: str = "Enterprise Compliance Auditor"
    # Kept narrow on purpose: a broad "policies / HR rules" wording pulls plain policy questions away from doc_agent
    description: str = (
        "Gives a formal verdict [COMPLIANT / WARNING / VIOLATION] on a specific action or scenario the user "
        "describes, by checking it against company policies and regulations (GDPR/KVKK)."
    )

    def __init__(self, chat_model=None, rag_engine: Optional[RAGEngine] = None):
        super().__init__(chat_model=chat_model)
        self._rag_engine = rag_engine

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
        search_result = engine.search(question)
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
            context=context,
            language_rule=language_instruction(language),
            **REPORT_HEADINGS.get(language, REPORT_HEADINGS["en"]),
        )
        try:
            response = self.chat_model.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=f"Scenario / Request to Audit: {question}"),
                ]
            )
            audit_report = response.content.strip()
        except Exception as e:
            logger.error(f"[{self.name}] Compliance audit LLM error: {e}")
            audit_report = message("compliance_error", language)

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "compliance_audit",
            "sources_count": len(sources),
            "duration_ms": duration_ms,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "final_answer": audit_report,
            "sources": sources,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
