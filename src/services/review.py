"""Questions to review: answers that could not be (fully) verified, unanswered questions, and answers rated down.

They come from the audit log; questions staff have answered in the FAQ are left out (src/services/faq.py).
"""

import re
from typing import Any, Dict, List, Optional

from src.agent.answer_cache import normalize_question
from src.core.audit import audit_logger
from src.services.faq import faq_store

# "[doc_agent] Soru?" (questions) and "[NEGATIVE] Q: Soru?" (feedback); without stored questions only the length
_DETAIL_PREFIX = re.compile(r"^(?:\[[^\]]*\]\s*)+(?:Q:\s*)?")
_NOT_STORED = "(question not stored"


def question_of(detail: Optional[str]) -> str:
    """The question text of an audit detail, or "" when questions are not stored (AUDIT_STORE_QUESTIONS=false)."""
    text = _DETAIL_PREFIX.sub("", str(detail or "")).strip()
    return "" if text.startswith(_NOT_STORED) else text


async def review_items(limit: int) -> List[Dict[str, Any]]:
    """Most recent items first: {..audit entry, "reason": "unverified" | "negative_feedback", "question"}."""
    unverified = []
    for action in ("query", "query_stream"):
        unverified += await audit_logger.aquery_logs(action=action, status="warning", limit=limit)
    feedback = await audit_logger.aquery_logs(action="feedback", limit=limit * 3)
    negative = [entry for entry in feedback if str(entry.get("detail", "")).startswith("[NEGATIVE]")]
    items = [{**entry, "reason": "unverified"} for entry in unverified]
    items += [{**entry, "reason": "negative_feedback"} for entry in negative]

    answered = faq_store.answered()
    result = []
    for item in items:
        question = question_of(item.get("detail"))
        if question and (item.get("username"), normalize_question(question)) in answered:
            continue
        result.append({**item, "question": question})
    result.sort(key=lambda entry: entry.get("timestamp", ""), reverse=True)
    return result[:limit]


async def askers_of(question: str, limit: int = 500) -> List[Dict[str, str]]:
    """Every user in the review list who asked this question (same words after normalization)."""
    wanted = normalize_question(question)
    return [
        {"username": item["username"], "question": item["question"]}
        for item in await review_items(limit)
        if item.get("username") and item["question"] and normalize_question(item["question"]) == wanted
    ]
