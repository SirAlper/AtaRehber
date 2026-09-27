"""Service request agent: files requests ("talep") from the chat and reports the status of the user's requests.

It performs an action with side effects, so it stays deliberately narrow:
- It first shows the drafted request and files it only after the user confirms ("evet" / "yes") in the next
  message; the draft is kept in the conversation state (pending_request) until then.
- Filing only creates a record in the local request store (staff work it off) and e-mails the configured unit.
- It never sends e-mail to addresses taken from the conversation and never contacts external services.
Without a conversation session (API calls without session_id) there is no next message to confirm in, so the
request is filed directly; such clients state their intent explicitly (or use POST /api/v1/requests).
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.language import confirmation_reply, language_name, message, response_language
from src.agent.llm import json_mode
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.agent.prompts import ORGANIZATION
from src.core import config
from src.core.audit import audit_logger
from src.core.logger import get_logger
from src.services.notifier import notify_new_request
from src.services.service_requests import get_request_store, normalize_category

logger = get_logger("MultiAgent.RequestAgent")

REQUEST_EXTRACTION_PROMPT = """You turn a user's message into a service request for {organization}.
Decide the action:
- "create": the user wants to open, file, or report something (a fault, a maintenance need, an access, account, or booking request).
- "list": the user asks about the status of their own existing requests.
Allowed categories: {categories}. Pick the closest one; use "other" when none fits.
Write the title and description in {language}. The title is a short summary (at most 12 words). The description
contains only details the user actually gave (place, device, time, what is wrong); never invent details.

Output ONLY this JSON, with no other text:
{{"action": "create", "category": "<category>", "title": "<title>", "description": "<description>"}}
"""

LIST_KEYWORDS = ("taleplerim", "talebimin", "taleplerimin", "durumu", "my requests", "my tickets", "status of my")


@register_agent
class ServiceRequestAgent(BaseSubAgent):
    """Specialist sub-agent that files service requests (after confirmation) and lists the user's own requests."""

    name: str = "request_agent"
    display_name: str = "Service Request Agent"
    description: str = (
        "Opens a service request / ticket when the user explicitly asks to open, file, or report something "
        "(e.g. a broken device, a maintenance need, an account or access request), and lists the status of the "
        "user's own requests. Not for questions about rules or procedures."
    )

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()
        language = response_language(question, state.get("chat_history", []))
        user = state.get("user") or {}
        username = user.get("username")

        if not username:
            return self._result(
                state, message("request_login_required", language), "request", "not_authenticated", start_time
            )

        # 1. Answer to a drafted request ("evet" / "hayır")
        pending: Optional[Dict[str, Any]] = state.get("pending_request")
        reply = confirmation_reply(question) if pending else None
        if pending and reply == "confirm":
            return self._file(state, pending, user, language, start_time)
        if pending and reply == "reject":
            return self._result(
                state, message("request_discarded", language), "request_discard", "success", start_time, pending=None
            )

        # 2. New request or status question
        extracted = self._extract(question, language)
        if extracted["action"] == "list":
            return self._list(state, username, language, start_time)

        title = " ".join(extracted.get("title", "").split())[:200]
        if len(title) < 3:
            return self._result(
                state, message("request_unclear", language), "request_create", "needs_input", start_time, pending=None
            )
        draft = {
            "category": normalize_category(extracted.get("category")),
            "title": title,
            # Keep the user's own words next to the model's summary so nothing is lost
            "description": f"{extracted.get('description', '').strip()}\n\n---\n{question}".strip(),
            "summary": extracted.get("description", "").strip() or question,
        }
        if not state.get("has_session"):
            return self._file(state, draft, user, language, start_time)

        confirm_text = message(
            "request_confirm",
            language,
            title=draft["title"],
            category=draft["category"],
            description=draft["summary"],
        )
        return self._result(state, confirm_text, "request_draft", "awaiting_confirmation", start_time, pending=draft)

    def _file(self, state, draft, user, language, start_time) -> Dict[str, Any]:
        """Create the request record, notify the responsible unit, and audit it."""
        store = get_request_store()
        username = user["username"]
        try:
            record = store.create(
                username=username,
                category=draft["category"],
                title=draft["title"],
                description=draft["description"],
            )
        except Exception as e:
            logger.error(f"[{self.name}] Could not save request: {e}")
            return self._result(
                state, message("request_error", language), "request_create", "error", start_time, pending=None
            )

        notified = False
        try:
            notified = notify_new_request(record)
            if notified:
                store.mark_notified(record["id"])
        except Exception as e:
            logger.error(f"[{self.name}] Notification for request #{record['id']} failed: {e}")

        try:
            audit_logger.log(
                username=username,
                role=user.get("role", ""),
                action="request_create",
                detail=f"#{record['id']} [{record['category']}]"
                + (f" {record['title']}" if config.AUDIT_STORE_QUESTIONS else ""),
                status="success",
            )
        except Exception as e:
            logger.error(f"[{self.name}] Audit log for request #{record['id']} failed: {e}")

        parts = [
            message("request_created", language, id=record["id"], title=record["title"], category=record["category"])
        ]
        if notified:
            parts.append(message("request_notified", language))
        parts.append(message("request_follow_up", language))
        return self._result(
            state,
            "\n\n".join(parts),
            "request_create",
            "success",
            start_time,
            pending=None,
            request_id=record["id"],
            notified=notified,
        )

    def _list(self, state, username, language, start_time) -> Dict[str, Any]:
        requests = get_request_store().list(username=username, limit=5)
        if not requests:
            answer = message("request_list_empty", language)
        else:
            lines = [
                f"- **#{r['id']}** `{r['status']}` {r['title']} ({r['category']})"
                + (f": {r['resolution_note']}" if r.get("resolution_note") else "")
                for r in requests
            ]
            answer = message("request_list_header", language) + "\n" + "\n".join(lines)
        return self._result(state, answer, "request_list", "success", start_time)

    def _extract(self, question: str, language: str) -> Dict[str, str]:
        """Ask the model for action/category/title/description; fall back to simple rules."""
        prompt = REQUEST_EXTRACTION_PROMPT.format(
            organization=ORGANIZATION,
            categories=", ".join(config.REQUEST_CATEGORIES),
            language=language_name(language),
        )
        try:
            response = json_mode(self.chat_model).invoke(
                [SystemMessage(content=prompt), HumanMessage(content=question)]
            )
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.IGNORECASE)
            data = json.loads(text)
            action = "list" if str(data.get("action", "")).lower() == "list" else "create"
            return {
                "action": action,
                "category": str(data.get("category", "")),
                "title": str(data.get("title", "")),
                "description": str(data.get("description", "")),
            }
        except Exception as e:
            logger.warning(f"[{self.name}] Request extraction failed ({e}), using rules")
            lowered = question.lower()
            if any(keyword in lowered for keyword in LIST_KEYWORDS):
                return {"action": "list"}
            return {"action": "create", "category": "", "title": question[:120], "description": ""}

    _KEEP = object()

    def _result(self, state, answer, action, status, start_time, pending=_KEEP, **details) -> Dict[str, Any]:
        """Agent output; `pending` (a draft or None) replaces the stored draft, omitted keeps it."""
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": action,
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **details,
        }
        output = {
            "final_answer": answer,
            "sources": [],
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
        if pending is not self._KEEP:
            output["pending_request"] = pending
        return output
