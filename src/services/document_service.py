"""Document Service.

Encapsulates document management, safe storage, validation, chunking,
vector indexing, and audit logging.
"""

import os
import time
import asyncio
from typing import Dict, Any
from fastapi import HTTPException, UploadFile

from src.api.state import get_rag_engine, get_db_connector, get_document_loader
from src.core.audit import audit_logger
from src.core.config import (
    DOCS_PATH,
    EMBEDDING_MODEL_NAME,
    LLM_MODEL_NAME,
    LLM_BACKEND,
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    MAX_UPLOAD_SIZE_MB,
    ALLOWED_UPLOAD_EXTENSIONS,
)
from src.core.logger import get_logger

logger = get_logger("Services.Document")


class DocumentService:
    """Service handling all document file workflows, vector indexing, and sanitization."""

    @staticmethod
    def get_system_stats() -> Dict[str, Any]:
        """Aggregate system, hardware accelerator, model parameters, and index stats."""
        engine = get_rag_engine()
        connector = get_db_connector()
        db_stats = engine.get_stats()

        is_cuda = False
        try:
            import torch

            is_cuda = torch.cuda.is_available()
        except ImportError:
            pass

        device = "CUDA (NVIDIA GPU)" if is_cuda else "CPU"
        db_conn_info = connector.test_connection()

        return {
            "status": "success",
            "device": device,
            "llm_backend": LLM_BACKEND,
            "embedding_model": EMBEDDING_MODEL_NAME,
            "llm_model": OLLAMA_MODEL if LLM_BACKEND == "ollama" else LLM_MODEL_NAME,
            "ollama_base_url": OLLAMA_BASE_URL if LLM_BACKEND == "ollama" else None,
            "total_chunks": db_stats.get("total_chunks", 0),
            "total_documents": db_stats.get("total_documents", 0),
            "documents": db_stats.get("document_chunks", {}),
            "database": db_conn_info,
        }

    @staticmethod
    def list_documents() -> Dict[str, Any]:
        """List all valid enterprise documents in data directory with metadata."""
        if not os.path.exists(DOCS_PATH):
            os.makedirs(DOCS_PATH, exist_ok=True)

        engine = get_rag_engine()
        db_stats = engine.get_stats()
        chunk_map = db_stats.get("document_chunks", {})

        files = []
        for filename in sorted(os.listdir(DOCS_PATH)):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_UPLOAD_EXTENSIONS or filename.startswith("."):
                continue

            file_path = os.path.join(DOCS_PATH, filename)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                files.append(
                    {
                        "filename": filename,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "chunk_count": chunk_map.get(filename, 0),
                        "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                    }
                )

        return {"status": "success", "count": len(files), "documents": files}

    @staticmethod
    async def delete_document(filename: str, username: str, user_role: str) -> Dict[str, Any]:
        """Validate, delete file from disk, and remove corresponding chunks from ChromaDB."""
        safe_filename = os.path.basename(filename).strip()
        if not safe_filename or safe_filename != filename or safe_filename.startswith("."):
            raise HTTPException(status_code=400, detail="Invalid filename format.")

        ext = os.path.splitext(safe_filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete non-document file '{safe_filename}'. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
            )

        file_path = os.path.join(DOCS_PATH, safe_filename)
        real_docs_path = os.path.realpath(DOCS_PATH)
        if os.path.commonpath([os.path.realpath(file_path), real_docs_path]) != real_docs_path:
            raise HTTPException(status_code=400, detail="Path traversal attempt detected.")

        file_deleted = False
        if os.path.exists(file_path):
            await asyncio.to_thread(os.remove, file_path)
            file_deleted = True

        engine = get_rag_engine()
        deleted_chunks = await asyncio.to_thread(engine.delete_document, safe_filename)

        if not file_deleted and deleted_chunks == 0:
            raise HTTPException(status_code=404, detail=f"'{safe_filename}' was not found.")

        await audit_logger.alog(
            username=username,
            role=user_role,
            action="delete",
            detail=f"Deleted file '{safe_filename}' ({deleted_chunks} chunks removed)",
            status="success",
        )

        logger.info(f"Deleted document '{safe_filename}' (Chunks deleted: {deleted_chunks})")
        return {
            "status": "success",
            "message": f"'{safe_filename}' was deleted successfully.",
            "deleted_chunks": deleted_chunks,
            "file_deleted": file_deleted,
        }

    @staticmethod
    async def save_and_index_document(file: UploadFile, username: str, user_role: str) -> Dict[str, Any]:
        """Validate uploaded file, save securely, extract chunks, and upsert to vector store."""
        if not os.path.exists(DOCS_PATH):
            os.makedirs(DOCS_PATH, exist_ok=True)

        raw_filename = file.filename or ""
        safe_filename = os.path.basename(raw_filename).strip()
        if not safe_filename or safe_filename.startswith("..") or "/" in safe_filename or "\\" in safe_filename:
            raise HTTPException(status_code=400, detail="Invalid or unsafe filename.")

        ext = os.path.splitext(safe_filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
            )

        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        file_path = os.path.join(DOCS_PATH, safe_filename)
        total_bytes = 0

        try:
            with open(file_path, "wb") as buffer:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        buffer.close()
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE_MB}MB.",
                        )
                    buffer.write(chunk)
        except HTTPException:
            raise
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            logger.error(f"File upload write error: {e}")
            raise HTTPException(status_code=500, detail="Failed to write uploaded file.")

        # Chunk loaded file in worker thread
        loader = get_document_loader()
        chunks, ids, metadatas = await asyncio.to_thread(loader.load_and_chunk_file, file_path)

        if not chunks:
            await audit_logger.alog(
                username=username,
                role=user_role,
                action="upload",
                detail=f"Uploaded '{safe_filename}' (no parseable text)",
                status="warning",
            )
            return {
                "status": "warning",
                "message": f"'{safe_filename}' uploaded, but no parseable text was extracted.",
                "chunk_count": 0,
            }

        # Vector index upsert in worker thread
        engine = get_rag_engine()
        await asyncio.to_thread(engine.delete_document, safe_filename)
        await asyncio.to_thread(engine.add_documents, chunks, ids, metadatas)

        await audit_logger.alog(
            username=username,
            role=user_role,
            action="upload",
            detail=f"Uploaded and indexed '{safe_filename}' ({len(chunks)} chunks, {round(total_bytes/1024, 1)} KB)",
            status="success",
        )

        logger.info(f"Successfully uploaded and indexed '{safe_filename}' ({len(chunks)} chunks).")
        return {
            "status": "success",
            "message": f"'{safe_filename}' successfully uploaded and indexed.",
            "filename": safe_filename,
            "chunk_count": len(chunks),
        }
