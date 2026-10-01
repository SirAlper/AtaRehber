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

from src.agent.language import category_label, confirmation_reply, language_name, message, response_language
from src.agent.llm import json_mode
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.agent.prompts import ORGANIZATION
from src.core import config
from src.core.audit import audit_logger
from src.core.logger import get_logger
from src.services.notifier import notify_new_request
from src.services.service_requests import OPEN_STATUSES, get_request_store, normalize_category

logger = get_logger("MultiAgent.RequestAgent")

REQUEST_EXTRACTION_PROMPT = """You turn a user's message into a service request for {organization}.
Decide the action:
- "create": the user wants to open, file, or report something (a fault, a maintenance need, an access, account, or booking request).
- "list": the user asks about the status of their own existing requests.
- "cancel": the user wants to cancel one of their requests ("talebimi iptal et", "cancel request #12").
- "note": the user adds information to one of their existing requests ("12 numaralı talebime ekle: ...").
For "cancel" and "note", give the request number as "request_id" if the user names it (else null); for "note",
"note" is the information to add, in the user's words.
Allowed categories: {categories}. Pick the closest one; use "other" when none fits.
Write the title and description in {language}, with correct spelling. The title states the user's problem or need
as the user sees it (at most 12 words); do not reinterpret it into something the user did not ask for. When the
message refers to the earlier conversation ("this", "about that", "bununla ilgili"), take the subject from the
recent conversation given before the message. The description contains only details the user actually gave
(place, device, time, what is wrong, or what the earlier answer lacked); never invent details.

Output ONLY this JSON, with no other text:
{{"action": "create", "category": "<category>", "title": "<title>", "description": "<description>",
"request_id": null, "note": ""}}
"""


def _request_id(value: Any, question: str) -> Optional[int]:
    """The request number the model gave, or one written in the message ("#12", "12 numaralı")."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.strip().lstrip("#").isdigit():
        return int(value.strip().lstrip("#"))
    match = re.search(r"#\s*(\d+)|\b(\d+)\s*(?:numaralı|nolu|no'lu|no\.?)\b", question, re.IGNORECASE)
    return int(match.group(1) or match.group(2)) if match else None


LIST_KEYWORDS = ("taleplerim", "talebimin", "taleplerimin", "durumu", "my requests", "my tickets", "status of my")


@register_agent
class ServiceRequestAgent(BaseSubAgent):
    """Specialist sub-agent that files service requests (after confirmation) and lists the user's own requests."""

    name: str = "request_agent"
    display_name: str = "Service Request Agent"
    description: str = (
        "Opens a service request / ticket when the user explicitly asks to open, file, or report something "
        "(e.g. a broken device, a maintenance need, an account or access request), lists the status of the "
        "user's own requests filed with this assistant (numbered like #12), cancels them, and adds information "
        "to them. Not for questions about rules or procedures, nor for records stored in database tables."
    )

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        language = response_language(question, chat_history)
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
            if pending.get("action") == "cancel":
                return self._cancel(state, pending["id"], user, language, start_time)
            return self._file(state, pending, user, language, start_time)
        if pending and reply == "reject":
            return self._result(
                state, message("request_discarded", language), "request_discard", "success", start_time, pending=None
            )

        # 2. New request or status question
        extracted = self._extract(question, language, chat_history)
        if extracted["action"] == "list":
            return self._list(state, username, language, start_time)
        if extracted["action"] in ("cancel", "note"):
            return self._change(state, extracted, user, language, start_time)

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
            category=category_label(draft["category"], language),
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
            message(
                "request_created",
                language,
                id=record["id"],
                title=record["title"],
                category=category_label(record["category"], language),
            )
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

    def _change(self, state, extracted, user, language, start_time) -> Dict[str, Any]:
        """Cancel one of the user's open requests (after confirmation) or add information to it."""
        action = extracted["action"]
        store = get_request_store()
        username = user["username"]
        request_id = extracted.get("request_id")
        if request_id is None:
            # Without a number, the user's only open request is meant; with several, ask which one
            open_requests = [r for r in store.list(username=username, limit=50) if r["status"] in OPEN_STATUSES]
            if len(open_requests) != 1:
                lines = "\n".join(f"- **#{r['id']}** {r['title']}" for r in open_requests[:10])
                text = message("request_which", language) + (f"\n{lines}" if lines else "")
                return self._result(state, text, f"request_{action}", "needs_input", start_time, pending=None)
            request_id = open_requests[0]["id"]
        record = store.get(request_id)
        if record is None or record["username"] != username:
            # Another user's request is not revealed
            text = message("request_not_found", language, id=request_id)
            return self._result(state, text, f"request_{action}", "not_found", start_time, pending=None)
        if record["status"] not in OPEN_STATUSES:
            text = message("request_closed", language, id=request_id)
            return self._result(state, text, f"request_{action}", "rejected", start_time, pending=None)

        if action == "cancel":
            if not state.get("has_session"):
                return self._cancel(state, request_id, user, language, start_time)
            text = message("request_cancel_confirm", language, id=request_id, title=record["title"])
            draft = {"action": "cancel", "id": request_id}
            return self._result(state, text, "request_cancel", "awaiting_confirmation", start_time, pending=draft)

        note = " ".join(str(extracted.get("note") or "").split())
        if len(note) < 3:
            text = message("request_note_unclear", language)
            return self._result(state, text, "request_note", "needs_input", start_time, pending=None)
        store.add_note(request_id, note, username)
        self._audit(user, "request_note", f"#{request_id}: note added")
        text = message("request_note_added", language, id=request_id)
        return self._result(state, text, "request_note", "success", start_time, pending=None, request_id=request_id)

    def _cancel(self, state, request_id, user, language, start_time) -> Dict[str, Any]:
        store = get_request_store()
        record = store.get(request_id)
        # The request may have changed since the draft (staff closed it)
        if record is None or record["username"] != user["username"] or record["status"] not in OPEN_STATUSES:
            text = message("request_closed", language, id=request_id)
            return self._result(state, text, "request_cancel", "rejected", start_time, pending=None)
        store.update_status(request_id, "cancelled", user["username"])
        self._audit(user, "request_update", f"#{request_id}: {record['status']} -> cancelled")
        text = message("request_cancelled", language, id=request_id)
        return self._result(state, text, "request_cancel", "success", start_time, pending=None, request_id=request_id)

    @staticmethod
    def _audit(user, action: str, detail: str) -> None:
        try:
            audit_logger.log(
                username=user["username"], role=user.get("role", ""), action=action, detail=detail, status="success"
            )
        except Exception as e:
            logger.error(f"[request_agent] Audit log failed: {e}")

    def _list(self, state, username, language, start_time) -> Dict[str, Any]:
        requests = get_request_store().list(username=username, limit=5)
        if not requests:
            answer = message("request_list_empty", language)
        else:
            lines = [
                f"- **#{r['id']}** `{r['status']}` {r['title']} ({category_label(r['category'], language)})"
                + (f": {r['resolution_note']}" if r.get("resolution_note") else "")
                for r in requests
            ]
            answer = message("request_list_header", language) + "\n" + "\n".join(lines)
        return self._result(state, answer, "request_list", "success", start_time)

    def _extract(self, question: str, language: str, chat_history=()) -> Dict[str, str]:
        """Ask the model for action/category/title/description; fall back to simple rules."""
        prompt = REQUEST_EXTRACTION_PROMPT.format(
            organization=ORGANIZATION,
            categories=", ".join(config.REQUEST_CATEGORIES),
            language=language_name(language),
        )
        # "Open a request about this" names its subject only in the earlier turns
        history = [
            f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')[:600]}"
            for turn in list(chat_history or [])[-3:]
            if turn.get("question") and turn.get("answer")
        ]
        user_text = ("Recent conversation:\n" + "\n".join(history) + "\n\nMessage:\n" if history else "") + question
        try:
            response = json_mode(self.chat_model).invoke(
                [SystemMessage(content=prompt), HumanMessage(content=user_text)]
            )
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.IGNORECASE)
            data = json.loads(text)
            action = str(data.get("action", "")).lower()
            action = action if action in ("list", "cancel", "note") else "create"
            return {
                "action": action,
                "category": str(data.get("category", "")),
                "title": str(data.get("title", "")),
                "description": str(data.get("description", "")),
                "request_id": _request_id(data.get("request_id"), question),
                "note": str(data.get("note") or ""),
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
