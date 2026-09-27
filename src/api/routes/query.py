"""AI Query API Routes.

Exposes endpoints for multi-agent query delegation, real-time stage event streaming,
specialist catalog discovery, and user feedback submission.
"""

import time
import json
import asyncio
import threading

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.schemas import QueryRequest, AgentsListResponse, AgentInfo, FeedbackRequest
from src.api.state import get_multi_agent_orchestrator, query_concurrency_gate
from src.agent.multi_agent.registry import agent_registry
from src.auth.dependencies import require_role
from src.auth.models import User
from src.core import config
from src.core.audit import audit_logger
from src.core.logger import get_logger

logger = get_logger("API.Query")
router = APIRouter(tags=["AI Query"])

QUERY_FAILED_DETAIL = "Query processing failed due to an internal error."
STREAM_FAILED_MESSAGE = "An internal error occurred while processing the query."


def _question_detail(question: str, agent: str | None = None) -> str:
    """Audit detail for a question; with AUDIT_STORE_QUESTIONS=false only its length is recorded."""
    prefix = f"[{agent}] " if agent else ""
    if config.AUDIT_STORE_QUESTIONS:
        return f"{prefix}{question}"
    return f"{prefix}(question not stored, {len(question)} chars)"


def _answer_preview(answer: str | None) -> str | None:
    return answer if config.AUDIT_STORE_QUESTIONS else None


def _resolve_forced_agent(request: QueryRequest) -> str | None:
    return request.agent if (request.agent and request.agent not in ("auto", "none")) else None


@router.get(
    "/api/v1/agents",
    summary="List Available Multi-Agent Specialists",
    response_model=AgentsListResponse,
)
async def list_available_agents(
    _: User = Depends(require_role("admin", "editor", "viewer")),
):
    """Return all registered specialist sub-agents available for query delegation."""
    agents = [
        AgentInfo(
            name="auto",
            display_name="👑 Auto (Supervisor Orchestrator)",
            description="Automatically analyzes question intent and delegates to the best specialist sub-agent or responds directly.",
            version="2.0.0",
        )
    ]
    for sub_agent in agent_registry.list_agents():
        info = sub_agent.get_info()
        agents.append(
            AgentInfo(
                name=info["name"],
                display_name=info["display_name"],
                description=info["description"],
                version=info.get("version", "1.0.0"),
            )
        )
    return {"agents": agents}


@router.post("/api/v1/query", summary="Query Enterprise AI Assistant")
async def query_rag(
    request: QueryRequest,
    http_req: Request,
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """Execute Multi-Agent LangGraph workflow and return verified answer, reference sources, and audit status."""
    start_time = time.time()
    ip_addr = http_req.client.host if http_req.client else None
    try:
        thread_id = f"{current_user.username}_{request.session_id}" if request.session_id else None
        forced_agent = _resolve_forced_agent(request)
        logger.info(
            f"Received question from '{current_user.username}' (role: {current_user.role}, thread: {thread_id}, "
            f"agent: {forced_agent or 'auto'}, length: {len(request.question)})"
        )
        logger.debug(f"Question: {request.question}")
        orchestrator = get_multi_agent_orchestrator()
        async with query_concurrency_gate:
            result = await asyncio.to_thread(
                orchestrator.query,
                request.question,
                thread_id=thread_id,
                forced_agent=forced_agent,
            )

        duration_ms = int((time.time() - start_time) * 1000)
        source_names = [s.get("source") for s in result.get("sources", []) if s.get("source")]
        active_agent = result.get("active_agent", "supervisor")

        await audit_logger.alog(
            username=current_user.username,
            role=current_user.role,
            action="query",
            detail=_question_detail(request.question, active_agent),
            sources=source_names,
            answer_preview=_answer_preview(result.get("answer", "")),
            ip_address=ip_addr,
            duration_ms=duration_ms,
            status="success",
        )

        return {
            "status": "success",
            "answer": result["answer"],
            "sources": result["sources"],
            "active_agent": active_agent,
            "agent_trace": result.get("agent_trace", []),
            "hallucination_grade": result.get("hallucination_grade", ""),
            "is_refined": result.get("is_refined", False),
        }
    except Exception:
        duration_ms = int((time.time() - start_time) * 1000)
        await audit_logger.alog(
            username=current_user.username,
            role=current_user.role,
            action="query",
            detail=_question_detail(request.question),
            ip_address=ip_addr,
            duration_ms=duration_ms,
            status="error",
        )
        logger.exception("Error during query execution")
        raise HTTPException(status_code=500, detail=QUERY_FAILED_DETAIL)


@router.post("/api/v1/query-stream", summary="Query Enterprise AI Assistant (Event Stream)")
async def query_rag_stream(
    request: QueryRequest,
    http_req: Request,
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """Stream Multi-Agent LangGraph stage events and deliver final answer via NDJSON format.
    All streamed queries are recorded in the compliance audit trail."""
    start_time = time.time()
    ip_addr = http_req.client.host if http_req.client else None

    thread_id = f"{current_user.username}_{request.session_id}" if request.session_id else None
    forced_agent = _resolve_forced_agent(request)
    logger.info(
        f"Received streaming question from '{current_user.username}' (thread: {thread_id}, "
        f"agent: {forced_agent or 'auto'}, length: {len(request.question)})"
    )
    logger.debug(f"Question: {request.question}")
    try:
        orchestrator = get_multi_agent_orchestrator()
    except Exception:
        logger.exception("Error initiating streaming query")
        await audit_logger.alog(
            username=current_user.username,
            role=current_user.role,
            action="query_stream",
            detail=_question_detail(request.question),
            ip_address=ip_addr,
            duration_ms=int((time.time() - start_time) * 1000),
            status="error",
        )
        raise HTTPException(status_code=500, detail=QUERY_FAILED_DETAIL)

    async def event_generator():
        final_answer = ""
        final_sources = []
        active_agent = "supervisor"
        had_error = False
        completed = False
        cancelled = threading.Event()

        async with query_concurrency_gate:
            loop = asyncio.get_running_loop()
            async_q: asyncio.Queue = asyncio.Queue()
            sentinel = object()

            def worker():
                events = orchestrator.stream_events(
                    request.question,
                    thread_id=thread_id,
                    forced_agent=forced_agent,
                )
                try:
                    for ev in events:
                        if cancelled.is_set():
                            break
                        loop.call_soon_threadsafe(async_q.put_nowait, ev)
                except Exception:
                    logger.exception("Error in stream worker")
                    loop.call_soon_threadsafe(
                        async_q.put_nowait,
                        {"type": "error", "message": STREAM_FAILED_MESSAGE},
                    )
                finally:
                    if hasattr(events, "close"):
                        events.close()
                    loop.call_soon_threadsafe(async_q.put_nowait, sentinel)

            worker_thread = threading.Thread(target=worker, daemon=True)
            worker_thread.start()

            try:
                while True:
                    item = await async_q.get()
                    if item is sentinel:
                        completed = True
                        break
                    if isinstance(item, dict):
                        if item.get("type") == "done":
                            final_answer = item.get("answer", "")
                            final_sources = item.get("sources", [])
                            active_agent = item.get("active_agent", "supervisor")
                        elif item.get("type") == "error":
                            had_error = True
                    yield json.dumps(item, ensure_ascii=False) + "\n"
            finally:
                # Client disconnected or stream closed early: stop the worker and keep holding the
                # concurrency gate until inference really finishes, so the model is never run concurrently.
                with anyio.CancelScope(shield=True):
                    if worker_thread.is_alive():
                        cancelled.set()
                        await anyio.to_thread.run_sync(worker_thread.join)

                    duration_ms = int((time.time() - start_time) * 1000)
                    source_names = [s.get("source") for s in final_sources if s.get("source")]
                    if had_error:
                        status = "error"
                    elif not completed:
                        status = "cancelled"
                    else:
                        status = "success"
                    await audit_logger.alog(
                        username=current_user.username,
                        role=current_user.role,
                        action="query_stream",
                        detail=_question_detail(request.question, active_agent),
                        sources=source_names,
                        answer_preview=_answer_preview(final_answer),
                        ip_address=ip_addr,
                        duration_ms=duration_ms,
                        status=status,
                    )

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@router.post("/api/v1/feedback", summary="Submit Answer Feedback")
async def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    current_user: User = Depends(require_role("admin", "editor", "viewer")),
):
    """Record user feedback for answer quality tracking."""
    ip_addr = request.client.host if request.client else None

    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="feedback",
        detail=f"[{body.feedback.upper()}] "
        + (f"Q: {body.question[:200]}" if config.AUDIT_STORE_QUESTIONS else "(question not stored)"),
        answer_preview=_answer_preview(body.comment[:500] if body.comment else None),
        ip_address=ip_addr,
        status="success",
    )

    logger.info(f"Feedback '{body.feedback}' from '{current_user.username}'")
    return {"status": "success", "message": "Feedback recorded."}
