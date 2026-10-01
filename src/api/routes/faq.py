"""FAQ: staff answers to the questions the documents did not answer, and the answers users get back."""

import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.state import get_rag_engine
from src.auth.dependencies import require_role
from src.auth.models import User
from src.core.audit import audit_logger
from src.core.logger import get_logger
from src.services.faq import MAX_ANSWER_LENGTH, MAX_QUESTION_LENGTH, faq_store, reindex_faq
from src.services.review import askers_of

logger = get_logger("API.FAQ")
router = APIRouter(tags=["FAQ"])

STAFF = ("admin", "editor")
ACCOUNTS = ("admin", "editor", "viewer")


class FaqAnswer(BaseModel):
    question: str = Field(..., min_length=3, max_length=MAX_QUESTION_LENGTH)
    answer: str = Field(..., min_length=1, max_length=MAX_ANSWER_LENGTH)
    groups: List[str] = Field(default_factory=list, description="Who may get this answer; empty: everyone")


class SeenRequest(BaseModel):
    ids: List[str] = Field(..., max_length=200)


async def _reindex() -> None:
    await asyncio.to_thread(reindex_faq, get_rag_engine(), faq_store)


@router.get("/api/v1/admin/faq", summary="List Staff Answers")
async def list_faq(_: User = Depends(require_role(*STAFF))):
    return {"entries": faq_store.list()}


@router.post("/api/v1/admin/faq", summary="Answer a Question", status_code=201)
async def add_faq(body: FaqAnswer, current_user: User = Depends(require_role(*STAFF))):
    """Store a staff answer and make it searchable. Every user in the review list who asked the same question is
    shown the answer, and the question leaves the review list."""
    try:
        entry = faq_store.add(
            body.question, body.answer, current_user.username, body.groups, asked=await askers_of(body.question)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _reindex()
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="faq_answer",
        detail=f"Answered '{entry['question'][:120]}' for {len(entry['asked'])} user(s)",
        status="success",
    )
    return {"entry": entry}


@router.put("/api/v1/admin/faq/{entry_id}", summary="Change a Staff Answer")
async def update_faq(entry_id: str, body: FaqAnswer, current_user: User = Depends(require_role(*STAFF))):
    try:
        entry = faq_store.update(entry_id, body.question, body.answer, body.groups)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if entry is None:
        raise HTTPException(status_code=404, detail="Answer not found.")
    await _reindex()
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="faq_update",
        detail=f"Changed the answer to '{entry['question'][:120]}'",
        status="success",
    )
    return {"entry": entry}


@router.delete("/api/v1/admin/faq/{entry_id}", summary="Delete a Staff Answer")
async def delete_faq(entry_id: str, current_user: User = Depends(require_role(*STAFF))):
    if not faq_store.delete(entry_id):
        raise HTTPException(status_code=404, detail="Answer not found.")
    await _reindex()
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="faq_delete",
        detail=f"Deleted staff answer {entry_id}",
        status="success",
    )
    return {"status": "success"}


@router.get("/api/v1/faq/answers", summary="Answers to My Questions")
async def my_answers(current_user: User = Depends(require_role(*ACCOUNTS))):
    """Staff answers to questions this user asked that they have not marked as seen."""
    return {"answers": faq_store.unseen_for(current_user.username)}


@router.post("/api/v1/faq/answers/seen", summary="Mark Answers as Seen")
async def mark_seen(body: SeenRequest, current_user: User = Depends(require_role(*ACCOUNTS))):
    return {"marked": faq_store.mark_seen(current_user.username, body.ids)}
