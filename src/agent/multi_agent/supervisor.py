import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.llm import create_chat_model
from src.agent.multi_agent.registry import AgentRegistry, agent_registry
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Supervisor")

# Tokens that make up conversational greetings (Turkish + English)
GREETING_TOKENS = frozenset(
    {
        "merhaba",
        "selam",
        "selamlar",
        "günaydın",
        "gunaydin",
        "iyi",
        "günler",
        "gunler",
        "akşamlar",
        "aksamlar",
        "nasılsın",
        "nasilsin",
        "naber",
        "hello",
        "hi",
        "hey",
        "good",
        "morning",
        "afternoon",
        "evening",
        "how",
        "are",
        "you",
        "greetings",
        "there",
        "everyone",
    }
)

SUPERVISOR_SYSTEM_PROMPT = """You are an Enterprise AI Supervisor Orchestrator.
Your task is to analyze the user's inquiry and route it to the most qualified specialist sub-agent, or answer directly if the inquiry is a general greeting or meta-question.

REGISTERED SPECIALIST SUB-AGENTS:
{agent_descriptions}

ROUTING AND DECISION RULES:
1. If the question matches the domain of one of the registered specialist agents above, select that agent's exact name in the 'agent' field:
   - Company policies, procedures, PDFs, guidelines, text documents -> doc_agent
   - Relational database tables, metrics, inventory, orders, SQL data -> db_agent
   - Verification of actions against rules, compliance, GDPR/KVKK, or ethics -> compliance_agent
   - (Or any other custom specialist agent listed above)
2. If the user inquiry is a conversational greeting (e.g., "hello", "hi", "how are you"), asks what the system can do, or is general chatter, choose 'agent': 'finish' and provide a polite, professional response in 'direct_response'.

OUTPUT FORMAT:
You MUST output your decision strictly in JSON format with no additional text or explanations:
```json
{{
  "agent": "<selected_agent_name or 'finish'>",
  "reason": "<brief rationale for routing>",
  "direct_response": "<direct response if agent is 'finish', otherwise empty string>"
}}
```
"""


class SupervisorAgent:
    """The central orchestrator responsible for user intent classification, delegation, and direct fallback responses."""

    def __init__(self, chat_model=None, registry: Optional[AgentRegistry] = None):
        self._chat_model = chat_model
        self.registry = registry or agent_registry

    @property
    def chat_model(self):
        if self._chat_model is None:
            self._chat_model = create_chat_model()
        return self._chat_model

    def route(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze question and decide routing target or return direct answer."""
        start_time = time.time()
        question = state.get("question", "").strip()
        forced_agent = state.get("forced_agent")

        # 1. Honor explicit user agent selection if provided
        if forced_agent and self.registry.get(forced_agent):
            logger.info(f"[Supervisor] Forced routing to agent: '{forced_agent}'")
            return {"next_agent": forced_agent}

        # 2. Pure greetings (every word is a greeting token) bypass LLM routing latency.
        # Any other content, e.g. "hi, list sales", goes through normal routing.
        words = re.sub(r"[^\w\s]", " ", question.lower()).split()
        is_greeting = bool(words) and len(words) <= 6 and all(w in GREETING_TOKENS for w in words)
        if is_greeting:
            duration_ms = int((time.time() - start_time) * 1000)
            direct_reply = (
                "Hello! I am your Enterprise AI Assistant. "
                "I am equipped with specialist agents covering enterprise documents (PDF/DOCX), "
                "SQL database analysis, and corporate compliance auditing. How can I assist you today?"
            )
            return {
                "next_agent": "finish",
                "final_answer": direct_reply,
                "sources": [],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": "supervisor",
                        "display_name": "Supervisor Orchestrator",
                        "action": "direct_greeting",
                        "duration_ms": duration_ms,
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # 3. Dynamic prompt with registered agents; recent turns let follow-ups ("and last month?") route correctly
        agent_descriptions = self.registry.get_supervisor_prompt()
        prompt = SUPERVISOR_SYSTEM_PROMPT.format(agent_descriptions=agent_descriptions)
        history_lines = [
            f"User: {turn.get('question', '')}\n(Handled by: {turn.get('agent', 'unknown')})"
            for turn in state.get("chat_history", [])[-3:]
            if turn.get("question")
        ]
        human_content = question
        if history_lines:
            human_content = "Recent conversation:\n" + "\n".join(history_lines) + f"\n\nCurrent question: {question}"

        try:
            response = self.chat_model.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=human_content),
                ]
            )
            content = response.content.strip()

            # Clean json fences
            json_text = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            json_text = re.sub(r"\s*```$", "", json_text).strip()

            data = json.loads(json_text)
            chosen_agent = data.get("agent", "doc_agent").strip()
            reason = data.get("reason", "")
            direct_response = data.get("direct_response", "").strip()

            logger.info(f"[Supervisor] Decision: agent='{chosen_agent}', reason='{reason}'")
        except Exception as e:
            logger.warning(f"[Supervisor] Routing JSON parse failed ({e}), using keyword heuristics")
            chosen_agent, reason, direct_response = self._heuristic_routing(question)

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": "supervisor",
            "display_name": "Supervisor Orchestrator",
            "action": "intent_routing",
            "target_agent": chosen_agent,
            "reason": reason,
            "duration_ms": duration_ms,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # If supervisor answered directly
        if chosen_agent == "finish":
            return {
                "next_agent": "finish",
                "final_answer": direct_response or "Response generated for your inquiry.",
                "sources": [],
                "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
            }

        # Validate chosen agent exists in registry; fallback to doc_agent if unknown
        if not self.registry.get(chosen_agent):
            if not self.registry.get("doc_agent"):
                logger.warning(f"[Supervisor] Agent '{chosen_agent}' not found and no 'doc_agent' fallback registered.")
                return {
                    "next_agent": "finish",
                    "final_answer": direct_response or "No suitable specialist agent is available for this request.",
                    "sources": [],
                    "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
                }
            logger.warning(f"[Supervisor] Agent '{chosen_agent}' not found in registry. Defaulting to 'doc_agent'.")
            chosen_agent = "doc_agent"

        return {
            "next_agent": chosen_agent,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }

    def _heuristic_routing(self, question: str) -> tuple[str, str, str]:
        """Fallback rule-based routing when LLM JSON parsing encounters issues."""
        q = question.lower()

        # Database keywords
        if any(
            w in q
            for w in (
                "tablo",
                "table",
                "sql",
                "satış",
                "sales",
                "ürün",
                "product",
                "stock",
                "stok",
                "price",
                "fiyat",
                "order",
                "sipariş",
                "count",
                "record",
            )
        ):
            return "db_agent", "Database and tabular query keywords detected.", ""

        # Compliance keywords
        if any(
            w in q
            for w in (
                "uygun mu",
                "compliant",
                "allowed",
                "prohibited",
                "yasak mı",
                "permission",
                "izin",
                "violation",
                "ihlal",
                "kvkk",
                "gdpr",
                "penalty",
                "policy",
            )
        ):
            return (
                "compliance_agent",
                "Compliance, policy, and audit keywords detected.",
                "",
            )

        # Default document RAG
        return "doc_agent", "Default enterprise document retrieval selected.", ""
