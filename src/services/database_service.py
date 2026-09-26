"""Database Service.

Encapsulates SQL execution guards, schema retrieval, table synchronization,
and vector indexing with non-blocking audit logging.
"""

import time
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from src.api.state import get_db_connector, get_db_loader, get_rag_engine
from src.connectors.db_loader import table_source_name
from src.core.audit import audit_logger
from src.core.logger import get_logger

logger = get_logger("Services.Database")


class DatabaseService:
    """Service providing relational database access and RAG synchronization."""

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Retrieve current connection state, dialect, and accessible table schema."""
        connector = get_db_connector()
        conn_info = connector.test_connection()
        schema_summary = connector.get_schema_summary() if connector.is_connected else ""
        return {
            "status": "success",
            "connection": conn_info,
            "schema_summary": schema_summary,
        }

    @staticmethod
    async def execute_query(
        query: str,
        username: str,
        user_role: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a safe read-only SQL query with audit tracking."""
        start_time = time.time()
        connector = get_db_connector()

        result = await asyncio.to_thread(connector.execute_query, query)
        duration_ms = int((time.time() - start_time) * 1000)

        if result.get("status") == "error":
            await audit_logger.alog(
                username=username,
                role=user_role,
                action="db_query",
                detail=f"Rejected query: {query}",
                ip_address=ip_address,
                duration_ms=duration_ms,
                status="error",
            )
            raise HTTPException(status_code=400, detail=result.get("message"))

        await audit_logger.alog(
            username=username,
            role=user_role,
            action="db_query",
            detail=f"Executed query: {query}",
            answer_preview=f"Returned {result.get('row_count', 0)} rows",
            ip_address=ip_address,
            duration_ms=duration_ms,
            status="success",
        )
        return {"status": "success", "data": result}

    @staticmethod
    async def sync_table(
        table_name: str,
        text_columns: Optional[List[str]],
        title_column: Optional[str],
        id_column: Optional[str],
        username: str,
        user_role: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract table rows, format contextual chunks, and upsert into ChromaDB."""
        start_time = time.time()
        connector = get_db_connector()
        loader = get_db_loader()
        engine = get_rag_engine()

        if not connector.is_connected:
            await audit_logger.alog(
                username=username,
                role=user_role,
                action="db_sync_table",
                detail=f"Failed sync table '{table_name}' (DB disconnected)",
                ip_address=ip_address,
                status="error",
            )
            raise HTTPException(status_code=400, detail="Database connection is not active.")

        chunks, ids, metadatas = await asyncio.to_thread(
            loader.load_table_as_chunks,
            table_name=table_name,
            text_columns=text_columns,
            title_column=title_column,
            id_column=id_column,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if not chunks:
            await audit_logger.alog(
                username=username,
                role=user_role,
                action="db_sync_table",
                detail=f"Table '{table_name}' had 0 rows or was inaccessible",
                ip_address=ip_address,
                duration_ms=duration_ms,
                status="warning",
            )
            return {
                "status": "warning",
                "message": f"Table '{table_name}' has 0 rows or could not be converted.",
                "chunk_count": 0,
            }

        # Remove all previously synced rows first so rows deleted from the table do not linger in the index
        await asyncio.to_thread(engine.delete_document, table_source_name(table_name))
        await asyncio.to_thread(engine.add_documents, chunks, ids, metadatas)

        await audit_logger.alog(
            username=username,
            role=user_role,
            action="db_sync_table",
            detail=f"Synced table '{table_name}' ({len(chunks)} chunks)",
            ip_address=ip_address,
            duration_ms=duration_ms,
            status="success",
        )

        logger.info(f"Synced table '{table_name}' ({len(chunks)} chunks into vector index).")
        return {
            "status": "success",
            "message": f"Table '{table_name}' indexed successfully ({len(chunks)} chunks).",
            "table_name": table_name,
            "chunk_count": len(chunks),
        }
