import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
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

### 📌 1. Audit Verdict
Explicitly select one of the following three categories:
- **[COMPLIANT]**: The request is fully compliant with company policies.
- **[WARNING / CONDITIONALLY COMPLIANT]**: Permissible only if specific security or administrative prerequisites/approvals are satisfied.
- **[VIOLATION / PROHIBITED]**: The request violates enterprise information security, data privacy (GDPR/KVKK), or code of conduct rules, and cannot be permitted.

### 📑 2. Underlying Policy & Clause References
Specify the document name, policy code, and relevant sections from the context above (e.g., SEC-POL-04 Section 4.1).

### 🔍 3. Risk & Impact Assessment
Analyze the security, legal, administrative, or operational risks the action poses to the enterprise.

### 💡 4. Mandatory Approvals & Action Plan
Required administrative approvals (CISO, DPO, HR, Legal) or proper procedure steps to execute this request safely.

If no specific rule is found in company documents, state that no written policy was identified and recommend consulting the Legal or Information Security team.
"""


@register_agent
class ComplianceAuditorAgent(BaseSubAgent):
    """Specialist sub-agent for auditing enterprise actions against compliance policies and producing structured verdicts."""

    name: str = "compliance_agent"
    display_name: str = "Enterprise Compliance Auditor"
    description: str = (
        "Used for officially auditing user scenarios, processes, or requests against enterprise security policies, "
        "privacy regulations (GDPR/KVKK), and HR rules, producing structured compliance audit reports "
        "[COMPLIANT / WARNING / VIOLATION]."
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

        logger.info(f"[{self.name}] Auditing compliance scenario: '{question}'")

        # 1. Search relevant compliance policies and regulations
        engine = self._get_engine()
        search_result = engine.search(question)
        context = search_result.get("context", "").strip()
        sources = search_result.get("sources", [])

        if not context:
            duration_ms = int((time.time() - start_time) * 1000)
            answer = (
                "### 📌 1. Audit Verdict\n**[UNDETERMINED]**\n\n"
                "### 📑 2. Supporting Documents\nNo relevant policy or regulatory document was found matching this inquiry in the knowledge base.\n\n"
                "### 🔍 3. Recommendation\nPlease contact the Legal & Compliance or Information Security department directly for guidance."
            )
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
        prompt = COMPLIANCE_SYSTEM_PROMPT.format(context=context)
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
            audit_report = "A system error occurred while generating the audit report. Please try again later."

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
