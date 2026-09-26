"""Documents and System API Routes.

Exposes endpoints for file uploads, vector index maintenance, and system telemetry.
Delegates business logic to DocumentService.
"""

from fastapi import APIRouter, Depends, UploadFile, File

from src.auth.dependencies import require_role
from src.auth.models import User
from src.services.document_service import DocumentService

router = APIRouter(tags=["Documents & System"])


@router.get("/api/v1/stats", summary="System and Vector Store Statistics")
def get_system_stats(_: User = Depends(require_role("admin", "editor", "viewer"))):
    """Return hardware acceleration details, active models, and index statistics."""
    return DocumentService.get_system_stats()


@router.get("/api/v1/documents", summary="List Indexed Documents")
def list_documents(_: User = Depends(require_role("admin", "editor", "viewer"))):
    """List uploadable user files in data/ directory along with their chunk counts in ChromaDB."""
    return DocumentService.list_documents()


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


@router.post("/api/v1/upload-file", summary="Upload and Index Document")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Upload a new PDF, DOCX, or TXT document, chunk it, and index it into ChromaDB."""
    return await DocumentService.save_and_index_document(
        file=file,
        username=current_user.username,
        user_role=current_user.role,
    )
