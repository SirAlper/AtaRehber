import asyncio
import contextlib
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Deque, Dict

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.auth.jwt_handler import decode_access_token
from src.core.config import CORS_ORIGINS, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_READS_PER_MINUTE
from src.core.logger import get_logger
from src.api.state import cleanup_services, init_services
from src.api.routes import (
    documents_router,
    query_router,
    database_router,
    auth_router,
    admin_router,
    requests_router,
)

logger = get_logger("API")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan context manager to initialize models on startup and cleanup on shutdown."""
    init_services()
    # Retention policy and scheduled backups (all off unless configured)
    from src.api.maintenance import maintenance_loop

    maintenance_task = asyncio.create_task(maintenance_loop())
    yield
    maintenance_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await maintenance_task
    cleanup_services()


API_VERSION = "2.1.1"

app = FastAPI(
    title="OpenLocalRagAgents API",
    description="Privacy-first, on-premise RAG and Agentic AI gateway with zero cloud dependencies.",
    version=API_VERSION,
    lifespan=lifespan,
)

# CORS configuration (reads allowed origins from config/env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────── RATE LIMITING MIDDLEWARE ────────────────────────────

_RATE_WINDOW = 60  # seconds
_RATE_LIMIT_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_rate_limit_store: Dict[str, Deque[float]] = defaultdict(deque)
_last_sweep = 0.0


def _rate_limit_key(request: Request) -> str:
    """Identify the caller: authenticated users are limited per account, anonymous callers per IP.

    Keying by account matters when many users reach the API through one gateway
    (e.g. the Streamlit frontend container), which would otherwise share a single IP budget.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token_data = decode_access_token(auth_header[7:].strip())
        if token_data is not None:
            return f"user:{token_data.username}"
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def _sweep_rate_limit_store(now: float) -> None:
    """Drop callers with no requests in the current window so the store cannot grow unbounded."""
    global _last_sweep
    if now - _last_sweep < _RATE_WINDOW:
        return
    _last_sweep = now
    for key in list(_rate_limit_store.keys()):
        timestamps = _rate_limit_store[key]
        if not timestamps or now - timestamps[-1] >= _RATE_WINDOW:
            del _rate_limit_store[key]


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Sliding-window rate limiting to prevent API abuse."""
    if request.url.path in _RATE_LIMIT_EXEMPT_PATHS:
        return await call_next(request)

    # Reads have their own, larger budget: the web UI reloads its panels with several GETs on every click,
    # which must not use up the budget for questions and uploads
    is_read = request.method in _READ_METHODS
    limit = RATE_LIMIT_READS_PER_MINUTE if is_read else RATE_LIMIT_PER_MINUTE
    key = f"{_rate_limit_key(request)}:{'read' if is_read else 'write'}"
    now = time.time()
    _sweep_rate_limit_store(now)

    timestamps = _rate_limit_store[key]
    while timestamps and now - timestamps[0] >= _RATE_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= limit:
        logger.warning(f"Rate limit exceeded for {key}")
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": f"Rate limit exceeded. Maximum {limit} requests per minute.",
                "retry_after": _RATE_WINDOW,
            },
            headers={"Retry-After": str(_RATE_WINDOW)},
        )

    timestamps.append(now)
    return await call_next(request)


@app.get("/health", tags=["System"], summary="Liveness Probe")
async def health():
    """Unauthenticated liveness probe for container orchestration healthchecks."""
    return {"status": "ok", "version": API_VERSION}


# Include modular API routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(query_router)
app.include_router(database_router)
app.include_router(requests_router)
