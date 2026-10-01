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
from src.auth.document_access import GUEST_ROLE
from src.agent.multi_agent.clarify import clarification_text, parse_clarification
from src.auth.profile import profile_note
from src.core.config import CLARIFY_QUESTIONS, MAX_AGENT_STEPS
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

# Thanks and goodbyes ("çok teşekkür ederim", "sağ olun", "thanks a lot"): every word is one of these, and at
# least one is a thanks or goodbye word, so "çok" or "you" alone is not taken for thanks
THANKS_WORDS = frozenset(
    {
        "teşekkür",
        "teşekkürler",
        "tesekkur",
        "tesekkurler",
        "tşk",
        "tşkler",
        "tsk",
        "sağol",
        "sagol",
        "sağolun",
        "sagolun",
        "eyvallah",
        "görüşürüz",
        "gorusuruz",
        "hoşçakal",
        "hoscakal",
        "hoşçakalın",
        "hoscakalin",
        "thanks",
        "thank",
        "thx",
        "bye",
        "goodbye",
    }
)
THANKS_TOKENS = THANKS_WORDS | frozenset(
    {"çok", "cok", "ederim", "ederiz"}
    | {"you", "very", "much", "a", "lot", "so", "for", "the", "help", "yardım", "yardımınız", "için", "icin"}
    | {"tamam", "anladım", "anladim", "harika", "süper", "super", "bilgi", "bilgiler", "ok", "okay", "great"}
)

SUPERVISOR_SYSTEM_PROMPT = """You are the supervisor of an AI assistant team at {organization}.
Your task is to analyze the user's message and route it to the most qualified specialist sub-agent(s), or answer directly if the message is a greeting or a question about what you can do.

REGISTERED SPECIALIST SUB-AGENTS:
{agent_descriptions}

ROUTING RULES (apply the first rule that matches; route only to agents listed above):
1. Greeting, small talk, or a question about what you can do -> 'finish', with a short polite reply in 'direct_response' written in {response_language}.
2. The user asks to open, file, or report a request or ticket, asks about the status of their own requests filed with this assistant (numbered like #12), or wants to cancel or add information to one of them -> request_agent. Records stored in the database tables listed under db_agent (for example a support ticket with a code) belong to rule 3, not here.
3. The answer is data stored in the database tables listed under db_agent: a count, total, price, quantity, status, or a specific record -> db_agent.
4. The user describes a specific action that they (or someone else) want to take and asks for a verdict on whether that action is allowed or compliant -> compliance_agent.
5. Everything else -> doc_agent. This includes every question about what a law, regulation, policy, or document says, even when it asks "how many", "how long", or "which" (how many members a board has, how many days of leave apply, which penalty applies). When unsure, choose doc_agent.
Custom agents listed above take precedence over rules 2-5 when the question clearly falls in their domain.
Questions may be in Turkish or English; route by meaning.

COMPOSITE QUESTIONS:
A question often asks two things at once, joined by "ve", "and", or a comma: for example what a rule or policy says AND a value stored in the database. First list the things the question asks and pick the agent for each with the routing rules above (asking whether one's own action is allowed or compliant is compliance_agent, not doc_agent). If they need different agents, return one step per agent (at most {max_steps}), each with a self-contained sub-question in the user's language; never drop a part of the question. If everything belongs to one agent, return exactly one step whose question is the user's question.
Order the steps so that each comes after the steps it needs. If a step needs the answer of an earlier step (to look something up with it, compare with it, or compute from it), add "uses": [<0-based numbers of those earlier steps>]. The final answer combines the steps and may draw the conclusion (compare, subtract, say whether a condition is met).
{clarify_rule}
EXAMPLES:
- "What was our total revenue last quarter?" -> db_agent
- "Bu yıl kaç yeni müşteri kazandık?" -> db_agent (data stored in the database)
- "Yönetim kurulu kaç üyeden oluşur?" -> doc_agent (asks what a regulation says)
- "Ziyaretçiler binaya hangi saatlerde girebilir?" -> doc_agent (asks what the rule is)
- "Ziyaretçimi mesai saatleri dışında binaya almam uygun mu?" -> compliance_agent (verdict on the user's own action)
- "B204'teki projektör çalışmıyor, arıza kaydı açar mısın?" -> request_agent
- "TKT-2025-77 kodlu destek kaydı ne durumda?" -> db_agent (a record stored in a database table, not one of the user's requests)
- "What can you help me with?" -> finish
- "Şifreler kaç günde bir değiştirilmeli ve satış tablosunda kaç sipariş var?" -> step 0: doc_agent (how often passwords must be changed), step 1: db_agent (how many orders the sales table has)
- "What is the hotel limit for domestic trips, and what is the unit price of the cheapest product?" -> step 0: doc_agent (hotel limit), step 1: db_agent (unit price of the cheapest product)
- "Stoğu en az olan ürün hangisi ve iade politikası ne diyor?" -> step 0: db_agent (which product has the lowest stock), step 1: doc_agent (the return policy for that product), "uses": [0]

OUTPUT FORMAT:
You MUST output your decision strictly in JSON format with no additional text or explanations:
```json
{{
  "steps": [{{"agent": "<agent name>", "question": "<self-contained question for this agent>"}}],
  "reason": "<brief rationale for routing>",
  "direct_response": "",
  "clarify": null
}}
```
For 'finish', output an empty "steps" list and the reply in "direct_response".
"""

# Added to the routing prompt when the user can answer a question back (a conversation, no agent chosen)
CLARIFY_RULE = """
CLARIFYING QUESTIONS:
Ask the user ONE short question back instead of routing only when the question can mean things that have different answers in the rules (for example "İzin süresi ne kadar?" when annual, excuse, and sick leave differ; "Kayıtlar ne zaman?" when undergraduate and graduate dates differ) AND neither the recent conversation nor what is known about the user settles it. Then return no steps and "clarify": {{"question": "<your question in {response_language}>", "options": ["<2 to 4 short answers the user can pick>"]}}.
Most questions are clear enough: when there is one reasonable reading, route it and leave "clarify" null. Never ask about greetings, requests, or questions that name what they mean ("Yıllık izin kaç gün?" is clear).
"""

REQUEST_KEYWORDS = (
    "talep aç",
    "talep oluştur",
    "arıza kaydı",
    "kayıt aç",
    "taleplerim",
    "talebimin",
    "talebimi iptal",
    "talebime ekle",
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


def _indices(value: Any) -> List[int]:
    """Step numbers from the model's "uses" (a list of ints, or a single int)."""
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, int) and not isinstance(item, bool)]


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
        # The answer to a clarifying question is used in this turn only
        if state.get("pending_clarification") and "pending_clarification" not in decision:
            decision["pending_clarification"] = None
        return decision

    def _route(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()
        forced_agent = state.get("forced_agent")
        language = response_language(question, state.get("chat_history", []))

        words = re.sub(r"[^\w\s]", " ", question.lower()).split()
        is_greeting = bool(words) and len(words) <= 6 and all(w in GREETING_TOKENS for w in words)
        # "sağ ol" and "hoşça kal" are written apart as often as together
        thanks_words = re.sub(r"\b(sağ|sag|hoşça|hosca) (ol|olun|kal|kalın|kalin)\b", r"\1\2", " ".join(words)).split()
        is_thanks = (
            bool(thanks_words)
            and len(thanks_words) <= 8
            and all(w in THANKS_TOKENS for w in thanks_words)
            and any(w in THANKS_WORDS for w in thanks_words)
        )

        # The user answered a question back: the original question is routed together with the answer, and the
        # turn is marked so no agent asks again
        pending = state.get("pending_clarification") or {}
        clarified = bool(pending.get("question")) and not (is_greeting or is_thanks)
        if clarified:
            question = f"{pending['question']} ({question})"

        # 1. Honor explicit user agent selection if provided (a greeting still gets a greeting: guests always
        # have doc_agent forced, and "merhaba" is no document question)
        if forced_agent and self.registry.get(forced_agent) and not (is_greeting or is_thanks):
            logger.info(f"[Supervisor] Forced routing to agent: '{forced_agent}'")
            return {
                "next_agent": forced_agent,
                "plan": [{"agent": forced_agent, "question": question}],
                "clarified": clarified,
            }

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

        # 3. Pure greetings and thanks (every word a greeting or thanks token) bypass LLM routing latency.
        # Any other content, e.g. "hi, list sales", goes through normal routing.
        if is_greeting or is_thanks:
            user = state.get("user") or {}
            # Guests only ask about documents; their greeting does not offer requests or databases
            is_guest = user.get("role") == GUEST_ROLE
            if is_greeting:
                answer = message("greeting_guest" if is_guest else "greeting", language)
            else:
                answer = message("thanks", language)
            # Tell users who can file requests that they can, where they will read it
            if user.get("username") and not is_guest and self.registry.is_available("request_agent"):
                answer += "\n\n" + message("request_hint", language)
            return {
                "next_agent": "finish",
                "plan": [],
                "final_answer": answer,
                "sources": [],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": "supervisor",
                        "display_name": "Supervisor Orchestrator",
                        "action": "direct_greeting" if is_greeting else "direct_thanks",
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # 4. A question back needs a next message (a conversation) and no agent chosen by the user; never twice in
        # a row
        allow_clarify = CLARIFY_QUESTIONS and bool(state.get("has_session")) and not clarified

        # 5. Dynamic prompt with the available agents; recent turns let follow-ups ("and last month?") route correctly
        language_label = language_name(language)
        prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            organization=ORGANIZATION,
            agent_descriptions=self.registry.get_supervisor_prompt(),
            response_language=language_label,
            max_steps=self.max_steps,
            clarify_rule=CLARIFY_RULE.format(response_language=language_label) if allow_clarify else "",
        )
        history_lines = [
            f"User: {turn.get('question', '')}\n(Handled by: {turn.get('agent', 'unknown')})"
            for turn in state.get("chat_history", [])[-3:]
            if turn.get("question")
        ]
        human_content = question
        if history_lines:
            human_content = "Recent conversation:\n" + "\n".join(history_lines) + f"\n\nCurrent question: {question}"
        user_note = profile_note(state.get("user"))
        if user_note:
            human_content = f"{user_note}\n\n{human_content}"

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
            clarification = parse_clarification(data.get("clarify")) if allow_clarify and not raw_steps else None
            logger.info(f"[Supervisor] Decision: steps={raw_steps}, clarify={clarification}, reason='{reason}'")
        except Exception as e:
            logger.warning(f"[Supervisor] Routing JSON parse failed ({e}), using keyword heuristics")
            agent, reason = self._heuristic_routing(question)
            raw_steps, direct_response, clarification = [{"agent": agent, "question": question}], "", None

        if clarification:
            return {
                "next_agent": "finish",
                "plan": [],
                "final_answer": clarification_text(clarification),
                "sources": [],
                "clarification": clarification,
                "pending_clarification": {"question": question},
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": "supervisor",
                        "display_name": "Supervisor Orchestrator",
                        "action": "clarify",
                        "reason": reason,
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

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
            trace_entry["plan"] = [
                {"agent": step["agent"], "question": step["question"], "uses": step["uses"]} for step in plan
            ]

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
            "clarified": clarified,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }

    def _validate_plan(self, raw_steps: Any, question: str) -> List[Dict[str, Any]]:
        """Keep steps for available agents (unknown ones fall back to doc_agent), drop duplicates, cap the count.

        Each step gets an "id" (its position) and "uses": the ids of earlier kept steps whose answers it needs.
        """
        plan: List[Dict[str, Any]] = []
        kept_ids: Dict[int, int] = {}  # position in the model's list -> id in the plan
        for position, step in enumerate(raw_steps if isinstance(raw_steps, list) else []):
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
            # One step per agent: the model sometimes splits a single-topic question into sub-questions for the
            # same agent, which only adds a synthesis step. That agent then answers the whole question.
            if any(existing["agent"] == agent for existing in plan):
                continue
            if len(plan) >= self.max_steps:
                break
            uses = sorted({kept_ids[u] for u in _indices(step.get("uses")) if u in kept_ids})
            kept_ids[position] = len(plan)
            plan.append({"agent": agent, "question": sub_question, "id": len(plan), "uses": uses})
        if len(plan) == 1:
            # A single step answers the user's own question; the model sometimes shortens it
            plan[0]["question"] = question
        return plan

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
