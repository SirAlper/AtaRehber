"""Documents and System API Routes.

Exposes endpoints for file uploads, vector index maintenance, document access groups, and system telemetry.
Delegates business logic to DocumentService.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile

from src.api.schemas import DocumentAccessRequest
from src.auth.dependencies import require_role
from src.auth.models import User
from src.services.document_service import DocumentService

router = APIRouter(tags=["Documents & System"])


@router.get("/api/v1/stats", summary="System and Vector Store Statistics")
def get_system_stats(current_user: User = Depends(require_role("admin", "editor", "viewer"))):
    """Return hardware acceleration details, active models, and index statistics (documents the caller may search)."""
    return DocumentService.get_system_stats(role=current_user.role, groups=current_user.groups)


@router.get("/api/v1/documents", summary="List Indexed Documents")
def list_documents(current_user: User = Depends(require_role("admin", "editor", "viewer"))):
    """List the documents the caller may search, with chunk counts and access groups."""
    return DocumentService.list_documents(role=current_user.role, groups=current_user.groups)


@router.delete("/api/v1/documents/{filename}", summary="Delete Document and Vector Chunks")
async def delete_document(
    filename: str,
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Permanently delete specified user file from data/ directory and remove chunks from ChromaDB."""
    return await DocumentService.delete_document(
        filename=filename,
        username=current_user.username,
        user_role=current_user.role,
    )


@router.put("/api/v1/documents/{filename}/access", summary="Set Document Access Groups")
async def set_document_access(
    filename: str,
    body: DocumentAccessRequest,
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Restrict a document to user groups, or make it visible to everyone again with an empty list."""
    return await DocumentService.set_document_access(
        filename=filename,
        groups=body.groups,
        username=current_user.username,
        user_role=current_user.role,
    )


@router.post("/api/v1/upload-file", summary="Upload and Index Document")
async def upload_file(
    file: UploadFile = File(...),
    groups: str = Form("", description="Comma-separated user groups allowed to search the document; empty: everyone"),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Upload a new PDF, DOCX, or TXT document, chunk it, and index it into ChromaDB."""
    return await DocumentService.save_and_index_document(
        file=file,
        username=current_user.username,
        user_role=current_user.role,
        groups=groups,
    )
