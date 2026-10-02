"""Document Service.

Encapsulates document management, safe storage, validation, chunking,
vector indexing, and audit logging.
"""

import os
import time
import asyncio
from typing import Any, Dict, Iterable, Optional
from fastapi import HTTPException, UploadFile

from src.agent.llm import check_ollama, grader_model_name, router_model_name
from src.api.state import get_rag_engine, get_db_connector, get_document_loader
from src.core.audit import audit_logger
from src.auth.document_access import access_metadata, document_access_store, normalize_groups
from src.core.config import (
    DOCS_PATH,
    EMBEDDING_MODEL_NAME,
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    MAX_UPLOAD_SIZE_MB,
    ALLOWED_UPLOAD_EXTENSIONS,
    RAG_DEVICE,
)
from src.core.logger import get_logger

logger = get_logger("Services.Document")

# Files saved to disk whose chunks are still being embedded (minutes for a long document on the CPU): they are
# listed, but cannot be searched yet
_indexing: set = set()


class DocumentService:
    """Service handling all document file workflows, vector indexing, and sanitization."""

    @staticmethod
    def get_system_stats(role: Optional[str] = None, groups: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """Aggregate model settings, LLM availability, index, and database stats.

        role/groups: the caller; documents the caller may not search are left out of the counts.
        """
        engine = get_rag_engine()
        connector = get_db_connector()
        db_stats = _visible_stats(engine.get_stats(), role, groups)
        db_conn_info = connector.test_connection()
        llm_problem = check_ollama(timeout=2.0)

        return {
            "status": "success",
            # Device of the embedding and reranker models; the LLM runs wherever Ollama runs
            "device": "CUDA (NVIDIA GPU)" if RAG_DEVICE.startswith("cuda") else "CPU",
            "llm_backend": "ollama",
            "embedding_model": EMBEDDING_MODEL_NAME,
            "llm_model": OLLAMA_MODEL,
            "router_model": router_model_name(),
            "grader_model": grader_model_name(),
            "ollama_base_url": OLLAMA_BASE_URL,
            "llm_status": llm_problem or "ok",
            "total_chunks": db_stats.get("total_chunks", 0),
            "total_documents": db_stats.get("total_documents", 0),
            "documents": db_stats.get("document_chunks", {}),
            "database": db_conn_info,
        }

    @staticmethod
    def list_documents(role: Optional[str] = None, groups: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """List the documents in the data directory the caller may search, with chunk counts and access groups."""
        if not os.path.exists(DOCS_PATH):
            os.makedirs(DOCS_PATH, exist_ok=True)

        engine = get_rag_engine()
        db_stats = engine.get_stats()
        chunk_map = db_stats.get("document_chunks", {})
        access = document_access_store.all()

        files = []
        for filename in sorted(os.listdir(DOCS_PATH)):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_UPLOAD_EXTENSIONS or filename.startswith("."):
                continue

            file_path = os.path.join(DOCS_PATH, filename)
            if os.path.isfile(file_path) and document_access_store.can_access(filename, role, groups):
                stat = os.stat(file_path)
                files.append(
                    {
                        "filename": filename,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "chunk_count": chunk_map.get(filename, 0),
                        # Still being embedded: not searchable yet
                        "indexing": filename in _indexing,
                        "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                        # Empty: visible to everyone
                        "groups": access.get(filename, []),
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
        # A later upload under the same name must not inherit the old restrictions
        document_access_store.remove(safe_filename)

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
    async def save_and_index_document(
        file: UploadFile, username: str, user_role: str, groups: Optional[Iterable[str]] = None
    ) -> Dict[str, Any]:
        """Validate uploaded file, save securely, extract chunks, and upsert to vector store.

        groups: user groups allowed to search the document; empty makes it visible to everyone.
        """
        try:
            groups = normalize_groups(groups)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
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

        _indexing.add(safe_filename)
        try:
            return await DocumentService._index_saved_file(
                file_path, safe_filename, total_bytes, groups, username, user_role
            )
        finally:
            _indexing.discard(safe_filename)

    @staticmethod
    async def _index_saved_file(
        file_path: str, safe_filename: str, total_bytes: int, groups: list, username: str, user_role: str
    ) -> Dict[str, Any]:
        """Chunk a saved upload and put its chunks into the vector store."""
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

        # Access groups are stored before indexing, so a restricted document is never searchable by everyone
        document_access_store.set(safe_filename, groups)
        if groups:
            for metadata in metadatas:
                metadata.update(access_metadata(groups))

        # Vector index upsert in worker thread
        engine = get_rag_engine()
        await asyncio.to_thread(engine.delete_document, safe_filename)
        await asyncio.to_thread(engine.add_documents, chunks, ids, metadatas)

        visibility = f"groups: {', '.join(groups)}" if groups else "visible to everyone"
        await audit_logger.alog(
            username=username,
            role=user_role,
            action="upload",
            detail=f"Uploaded and indexed '{safe_filename}' ({len(chunks)} chunks, "
            f"{round(total_bytes / 1024, 1)} KB, {visibility})",
            status="success",
        )

        logger.info(f"Successfully uploaded and indexed '{safe_filename}' ({len(chunks)} chunks).")
        return {
            "status": "success",
            "message": f"'{safe_filename}' successfully uploaded and indexed.",
            "filename": safe_filename,
            "chunk_count": len(chunks),
            "groups": groups,
        }

    @staticmethod
    async def set_document_access(
        filename: str, groups: Iterable[str], username: str, user_role: str
    ) -> Dict[str, Any]:
        """Change which user groups may search an indexed document (empty: everyone)."""
        try:
            groups = normalize_groups(groups)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        safe_filename = os.path.basename(filename).strip()
        if not safe_filename or safe_filename != filename or safe_filename.startswith("."):
            raise HTTPException(status_code=400, detail="Invalid filename format.")

        engine = get_rag_engine()
        if safe_filename not in engine.get_stats().get("document_chunks", {}):
            raise HTTPException(status_code=404, detail=f"'{safe_filename}' is not indexed.")

        previous = document_access_store.set(safe_filename, groups)
        updated_chunks = await asyncio.to_thread(
            engine.update_document_metadata, safe_filename, access_metadata(groups, previous)
        )
        visibility = f"groups: {', '.join(groups)}" if groups else "visible to everyone"
        await audit_logger.alog(
            username=username,
            role=user_role,
            action="document_access",
            detail=f"Access of '{safe_filename}' set to {visibility} (was: {', '.join(previous) or 'everyone'})",
            status="success",
        )
        logger.info(f"Access of '{safe_filename}' set to {visibility} ({updated_chunks} chunks updated).")
        return {
            "status": "success",
            "filename": safe_filename,
            "groups": groups,
            "updated_chunks": updated_chunks,
        }


def _visible_stats(stats: Dict[str, Any], role: Optional[str], groups: Optional[Iterable[str]]) -> Dict[str, Any]:
    """Index statistics limited to the documents the caller may search."""
    chunk_map = {
        name: count
        for name, count in stats.get("document_chunks", {}).items()
        if document_access_store.can_access(name, role, groups)
    }
    return {
        **stats,
        "document_chunks": chunk_map,
        "total_documents": len(chunk_map),
        "total_chunks": sum(chunk_map.values()),
    }
