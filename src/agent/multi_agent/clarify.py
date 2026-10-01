"""Questions back: when a question's answer depends on something the user did not say, ask once instead of guessing.

Two places can ask: the supervisor, from the question alone ("Bütçe ne kadar?" when several budgets exist), and
doc_agent, from the retrieved rules ("Kaç gün izin hakkım var?" when leave depends on seniority). Either way the
answer carries `clarification` and the state keeps `pending_clarification`; the supervisor routes the next message
together with the original question and marks the turn `clarified`, so nobody asks twice in a row.
"""

import re
from typing import Any, Dict, Optional

# A question about the asker's own situation: "hakkım", "alabilir miyim", "benim", "my", "can I"
_FIRST_PERSON = re.compile(
    r"(?i)\b(ben|benim|bana|beni|my|i|me|mine)\b|\w{2,}(ım|im|um|üm)\b|\b(miyim|mıyım|muyum|müyüm)\b"
)


def is_about_the_asker(question: str) -> bool:
    """Whether a question is about the asker's own case (only then is asking back worth a model call)."""
    return bool(_FIRST_PERSON.search(question.replace("İ", "i")))


def parse_clarification(value: Any) -> Optional[Dict[str, Any]]:
    """A clarifying question {"question", "options"} from a model's JSON, or None when it gave no usable one."""
    if not isinstance(value, dict) or value.get("ask") is False:
        return None
    question = " ".join(str(value.get("question") or "").split())
    if not 5 <= len(question) <= 300:
        return None
    raw = value.get("options") if isinstance(value.get("options"), list) else []
    options = list(dict.fromkeys(" ".join(str(o).split())[:80] for o in raw if str(o).strip()))[:4]
    return {"question": question, "options": options}


def clarification_text(clarification: Dict[str, Any]) -> str:
    """The question as answer text, with the options as a list for clients that show plain Markdown."""
    options = "".join(f"\n- {option}" for option in clarification["options"])
    return f"{clarification['question']}{chr(10) if options else ''}{options}"
