"""Service Request API Routes.

Users file requests (from the chat through the request agent, or with the form endpoint below) and follow their
own requests; staff (admin, editor) see all requests and change their status. Every change is audited.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.schemas import RequestStatus, ServiceRequestCreate, ServiceRequestUpdate
from src.auth.dependencies import require_role
from src.auth.models import User
from src.core import config
from src.core.audit import audit_logger
from src.core.notifier import notify_new_request
from src.core.service_requests import OPEN_STATUSES, get_request_store

router = APIRouter(prefix="/api/v1/requests", tags=["Service Requests"])

STAFF_ROLES = ("admin", "editor")


def _is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES


@router.get("", summary="List Service Requests")
async def list_requests(
    status: Optional[RequestStatus] = None,
    all_users: bool = Query(False, description="Staff only: include every user's requests"),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """The caller's own requests; staff can list everyone's with all_users=true."""
    username = None if (all_users and _is_staff(current_user)) else current_user.username
    records = await asyncio.to_thread(get_request_store().list, username, status, limit)
    return {"status": "success", "count": len(records), "requests": records, "categories": config.REQUEST_CATEGORIES}


@router.post("", summary="Create Service Request", status_code=201)
async def create_request(
    body: ServiceRequestCreate,
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """File a request without the chat (form); the responsible unit is e-mailed when configured."""
    store = get_request_store()
    try:
        record = await asyncio.to_thread(
            store.create, current_user.username, body.category, body.title, body.description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if await asyncio.to_thread(notify_new_request, record):
        await asyncio.to_thread(store.mark_notified, record["id"])
        record["notified"] = True
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="request_create",
        detail=f"#{record['id']} [{record['category']}]"
        + (f" {record['title']}" if config.AUDIT_STORE_QUESTIONS else ""),
        status="success",
    )
    return {"status": "success", "request": record}


@router.patch("/{request_id}", summary="Update Service Request Status")
async def update_request(
    request_id: int,
    body: ServiceRequestUpdate,
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """Staff set any status; the requester may only cancel their own open request."""
    store = get_request_store()
    record = await asyncio.to_thread(store.get, request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Request #{request_id} not found.")
    if not _is_staff(current_user):
        if record["username"] != current_user.username:
            # Do not reveal that another user's request exists
            raise HTTPException(status_code=404, detail=f"Request #{request_id} not found.")
        if body.status != "cancelled" or record["status"] not in OPEN_STATUSES:
            raise HTTPException(status_code=403, detail="You can only cancel your own open requests.")

    updated = await asyncio.to_thread(
        store.update_status, request_id, body.status, current_user.username, body.resolution_note
    )
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="request_update",
        detail=f"#{request_id}: {record['status']} -> {body.status}",
        status="success",
    )
    return {"status": "success", "request": updated}
