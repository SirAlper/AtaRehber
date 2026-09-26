"""Database API Routes.

Exposes endpoints for database status checking, read-only query testing,
and relational-to-vector table synchronization.
Delegates business logic to DatabaseService.
"""

from fastapi import APIRouter, Depends, Request

from src.api.schemas import SyncTableRequest, TestQueryRequest
from src.auth.dependencies import require_role
from src.auth.models import User
from src.services.database_service import DatabaseService

router = APIRouter(prefix="/api/v1/database", tags=["Database"])


@router.get("/status", summary="Database Connection Status and Schema")
def get_database_status(_: User = Depends(require_role("admin", "editor", "viewer"))):
    """Return database connection status, dialect type, and accessible tables."""
    return DatabaseService.get_status()


@router.post("/test-query", summary="Execute Safe Read-Only SQL Query")
async def run_database_query(
    req: TestQueryRequest,
    http_req: Request,
    current_admin: User = Depends(require_role("admin")),
):
    """Execute safe read-only SELECT query against the connected database."""
    ip_addr = http_req.client.host if http_req.client else None
    return await DatabaseService.execute_query(
        query=req.query,
        username=current_admin.username,
        user_role=current_admin.role,
        ip_address=ip_addr,
    )


@router.post("/sync-table", summary="Sync Database Table into Vector Index")
async def sync_database_table(
    req: SyncTableRequest,
    http_req: Request,
    current_admin: User = Depends(require_role("admin")),
):
    """Convert relational table rows into contextual text chunks and index into ChromaDB."""
    ip_addr = http_req.client.host if http_req.client else None
    return await DatabaseService.sync_table(
        table_name=req.table_name,
        text_columns=req.text_columns,
        title_column=req.title_column,
        id_column=req.id_column,
        username=current_admin.username,
        user_role=current_admin.role,
        ip_address=ip_addr,
    )
