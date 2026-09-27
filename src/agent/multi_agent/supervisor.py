import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.language import confirmation_reply, language_name, message, response_language
from src.agent.llm import create_chat_model, json_mode, router_model_name
from src.agent.multi_agent.registry import AgentRegistry, agent_registry
from src.agent.prompts import ORGANIZATION
from src.core.config import MAX_AGENT_STEPS
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

SUPERVISOR_SYSTEM_PROMPT = """You are the supervisor of an AI assistant team at {organization}.
Your task is to analyze the user's message and route it to the most qualified specialist sub-agent(s), or answer directly if the message is a greeting or a question about what you can do.

REGISTERED SPECIALIST SUB-AGENTS:
{agent_descriptions}

ROUTING RULES (apply the first rule that matches; route only to agents listed above):
1. Greeting, small talk, or a question about what you can do -> 'finish', with a short polite reply in 'direct_response' written in {response_language}.
2. The user asks to open, file, or report a request or ticket, or asks about the status of their own requests -> request_agent.
3. The answer is data stored in the database tables listed under db_agent: a count, total, price, quantity, status, or a specific record -> db_agent.
4. The user describes a specific action that they (or someone else) want to take and asks for a verdict on whether that action is allowed or compliant -> compliance_agent.
5. Everything else -> doc_agent. This includes every question about what a law, regulation, policy, or document says, even when it asks "how many", "how long", or "which" (how many members a board has, how many days of leave apply, which penalty applies). When unsure, choose doc_agent.
Custom agents listed above take precedence over rules 2-5 when the question clearly falls in their domain.
Questions may be in Turkish or English; route by meaning.

COMPOSITE QUESTIONS:
If answering needs more than one agent (for example what a regulation allows AND a number stored in the database), return up to {max_steps} steps, one per agent, each with a self-contained sub-question in the user's language. Otherwise return exactly one step whose question is the user's question.

EXAMPLES:
- "What was our total revenue last quarter?" -> db_agent
- "Bu yıl kaç yeni müşteri kazandık?" -> db_agent (data stored in the database)
- "Yönetim kurulu kaç üyeden oluşur?" -> doc_agent (asks what a regulation says)
- "Ziyaretçiler binaya hangi saatlerde girebilir?" -> doc_agent (asks what the rule is)
- "Ziyaretçimi mesai saatleri dışında binaya almam uygun mu?" -> compliance_agent (verdict on the user's own action)
- "B204'teki projektör çalışmıyor, arıza kaydı açar mısın?" -> request_agent
- "What can you help me with?" -> finish

OUTPUT FORMAT:
You MUST output your decision strictly in JSON format with no additional text or explanations:
```json
{{
  "steps": [{{"agent": "<agent name>", "question": "<self-contained question for this agent>"}}],
  "reason": "<brief rationale for routing>",
  "direct_response": ""
}}
```
For 'finish', output an empty "steps" list and the reply in "direct_response".
"""

REQUEST_KEYWORDS = (
    "talep aç",
    "talep oluştur",
    "arıza kaydı",
    "kayıt aç",
    "taleplerim",
    "talebimin",
    "ticket",
    "open a request",
    "file a request",
    "my requests",
)
DATABASE_KEYWORDS = (
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
    "record",
)
COMPLIANCE_KEYWORDS = (
    "uygun mu",
    "compliant",
    "allowed",
    "prohibited",
    "yasak mı",
    "permission",
    "violation",
    "ihlal",
    "penalty",
)


class SupervisorAgent:
    """The central orchestrator responsible for intent classification, planning, delegation, and direct replies.

    The routing decision is a plan: one step per specialist agent, each with its own sub-question. Most
    questions need one step; composite questions ("what does the regulation allow and how many did I use?")
    get up to MAX_AGENT_STEPS steps, whose answers the orchestrator combines.
    """

    def __init__(self, chat_model=None, registry: Optional[AgentRegistry] = None, max_steps: int = MAX_AGENT_STEPS):
        self._chat_model = chat_model
        self.registry = registry or agent_registry
        self.max_steps = max(1, max_steps)

    @property
    def chat_model(self):
        if self._chat_model is None:
            self._chat_model = create_chat_model(router_model_name())
        return self._chat_model

    def route(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze question and decide the plan of agent steps, or return a direct answer."""
        decision = self._route(state)
        # A drafted service request only survives the user's direct yes/no answer; anything else discards it
        if state.get("pending_request") and decision.get("next_agent") != "request_agent":
            decision["pending_request"] = None
        return decision

    def _route(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()
        forced_agent = state.get("forced_agent")
        language = response_language(question, state.get("chat_history", []))

        # 1. Honor explicit user agent selection if provided
        if forced_agent and self.registry.get(forced_agent):
            logger.info(f"[Supervisor] Forced routing to agent: '{forced_agent}'")
            return {"next_agent": forced_agent, "plan": [{"agent": forced_agent, "question": question}]}

        # 2. "Evet" / "hayır" answering a drafted service request goes straight back to the request agent
        if state.get("pending_request") and self.registry.get("request_agent") and confirmation_reply(question):
            return {
                "next_agent": "request_agent",
                "plan": [{"agent": "request_agent", "question": question}],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": "supervisor",
                        "display_name": "Supervisor Orchestrator",
                        "action": "confirmation_routing",
                        "target_agent": "request_agent",
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # 3. Pure greetings (every word is a greeting token) bypass LLM routing latency.
        # Any other content, e.g. "hi, list sales", goes through normal routing.
        words = re.sub(r"[^\w\s]", " ", question.lower()).split()
        is_greeting = bool(words) and len(words) <= 6 and all(w in GREETING_TOKENS for w in words)
        if is_greeting:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "next_agent": "finish",
                "plan": [],
                "final_answer": message("greeting", language),
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

        # 4. Dynamic prompt with the available agents; recent turns let follow-ups ("and last month?") route correctly
        prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            organization=ORGANIZATION,
            agent_descriptions=self.registry.get_supervisor_prompt(),
            response_language=language_name(language),
            max_steps=self.max_steps,
        )
        history_lines = [
            f"User: {turn.get('question', '')}\n(Handled by: {turn.get('agent', 'unknown')})"
            for turn in state.get("chat_history", [])[-3:]
            if turn.get("question")
        ]
        human_content = question
        if history_lines:
            human_content = "Recent conversation:\n" + "\n".join(history_lines) + f"\n\nCurrent question: {question}"

        try:
            response = json_mode(self.chat_model).invoke(
                [SystemMessage(content=prompt), HumanMessage(content=human_content)]
            )
            json_text = re.sub(r"^```(?:json)?\s*", "", response.content.strip(), flags=re.IGNORECASE)
            json_text = re.sub(r"\s*```$", "", json_text).strip()
            data = json.loads(json_text)
            raw_steps = data.get("steps")
            if raw_steps is None and data.get("agent"):  # older single-agent format
                raw_steps = [] if data["agent"] == "finish" else [{"agent": data["agent"], "question": question}]
            reason = str(data.get("reason", ""))
            direct_response = str(data.get("direct_response", "") or "").strip()
            logger.info(f"[Supervisor] Decision: steps={raw_steps}, reason='{reason}'")
        except Exception as e:
            logger.warning(f"[Supervisor] Routing JSON parse failed ({e}), using keyword heuristics")
            agent, reason = self._heuristic_routing(question)
            raw_steps, direct_response = [{"agent": agent, "question": question}], ""

        plan = self._validate_plan(raw_steps, question)
        trace_entry = {
            "agent": "supervisor",
            "display_name": "Supervisor Orchestrator",
            "action": "intent_routing",
            "target_agent": plan[0]["agent"] if plan else "finish",
            "reason": reason,
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if len(plan) > 1:
            trace_entry["plan"] = [{"agent": step["agent"], "question": step["question"]} for step in plan]

        if not plan:
            no_agents = not self.registry.list_available_agents()
            fallback_reply = message("no_agent" if no_agents else "direct_fallback", language)
            return {
                "next_agent": "finish",
                "plan": [],
                "final_answer": direct_response or fallback_reply,
                "sources": [],
                "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
            }

        return {
            "next_agent": plan[0]["agent"],
            "plan": plan,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }

    def _validate_plan(self, raw_steps: Any, question: str) -> List[Dict[str, str]]:
        """Keep steps for available agents (unknown ones fall back to doc_agent), drop duplicates, cap the count."""
        plan: List[Dict[str, str]] = []
        for step in raw_steps if isinstance(raw_steps, list) else []:
            if not isinstance(step, dict):
                continue
            agent = str(step.get("agent", "")).strip()
            if not agent or agent == "finish":
                continue
            if not self.registry.is_available(agent):
                if not self.registry.is_available("doc_agent"):
                    logger.warning(f"[Supervisor] Agent '{agent}' unavailable and no 'doc_agent' fallback.")
                    continue
                logger.warning(f"[Supervisor] Agent '{agent}' not available, defaulting to 'doc_agent'.")
                agent = "doc_agent"
            sub_question = str(step.get("question") or "").strip() or question
            if any(existing["agent"] == agent and existing["question"] == sub_question for existing in plan):
                continue
            plan.append({"agent": agent, "question": sub_question})
        if len(plan) == 1:
            # A single step answers the user's own question; the model sometimes shortens it
            plan[0]["question"] = question
        return plan[: self.max_steps]

    def _heuristic_routing(self, question: str) -> tuple:
        """Fallback rule-based routing when LLM JSON parsing encounters issues."""
        q = question.lower()
        if self.registry.is_available("request_agent") and any(w in q for w in REQUEST_KEYWORDS):
            return "request_agent", "Service request keywords detected."
        if self.registry.is_available("db_agent") and any(w in q for w in DATABASE_KEYWORDS):
            return "db_agent", "Database and tabular query keywords detected."
        if self.registry.is_available("compliance_agent") and any(w in q for w in COMPLIANCE_KEYWORDS):
            return "compliance_agent", "Compliance, policy, and audit keywords detected."
        return "doc_agent", "Default document retrieval selected."
