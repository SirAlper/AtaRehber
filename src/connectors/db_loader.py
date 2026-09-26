from typing import List, Dict, Any, Tuple, Optional
from src.connectors.db_connector import DatabaseConnector
from src.core.logger import get_logger

logger = get_logger("DatabaseTableLoader")


def table_source_name(table_name: str) -> str:
    """Vector-store 'source' metadata value used for chunks synced from a database table."""
    return f"db_{table_name}"


class DatabaseTableLoader:
    """ETL loader that reads relational database tables and transforms records into ChromaDB vector chunks."""

    def __init__(self, db_connector: DatabaseConnector):
        self.db = db_connector

    def load_table_as_chunks(
        self,
        table_name: str,
        text_columns: Optional[List[str]] = None,
        title_column: Optional[str] = None,
        id_column: Optional[str] = None,
    ) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        """Read rows from specified table, enrich with contextual headers, and convert to vector chunks."""
        chunks = []
        ids = []
        metadatas = []

        if not self.db.is_connected or not self.db.engine:
            logger.warning("No active database connection.")
            return chunks, ids, metadatas

        # Security check: table_name must be a valid identifier and present in accessible tables
        if not table_name or not table_name.isidentifier():
            logger.error(f"Invalid or unsafe table name format: '{table_name}'")
            return chunks, ids, metadatas

        accessible_tables = self.db.get_tables()
        if table_name not in accessible_tables:
            logger.error(f"Table '{table_name}' is not in accessible tables: {accessible_tables}")
            return chunks, ids, metadatas

        query_result = self.db.execute_query(f"SELECT * FROM {table_name}")
        if query_result["status"] != "success":
            logger.error(f"Query error: {query_result.get('message')}")
            return chunks, ids, metadatas

        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])

        if not rows:
            return chunks, ids, metadatas

        target_cols = text_columns if text_columns else columns

        # Detect primary key / ID column
        actual_id_col = id_column
        if not actual_id_col:
            for col in columns:
                if col.lower() in ("id", f"{table_name.lower()}_id", "pk"):
                    actual_id_col = col
                    break
            if not actual_id_col and columns:
                actual_id_col = columns[0]

        for idx, row in enumerate(rows):
            row_id_val = row.get(actual_id_col, idx + 1)
            chunk_id = f"db_{table_name}_row_{row_id_val}"

            title_text = f" | {row.get(title_column)}" if title_column and row.get(title_column) else ""
            header = f"[Database Table: {table_name} | Record: #{row_id_val}{title_text}]"

            row_content_lines = []
            for col in target_cols:
                val = row.get(col)
                if val is not None and str(val).strip():
                    row_content_lines.append(f"{col}: {val}")

            if not row_content_lines:
                continue

            full_chunk_text = f"{header}\n" + "\n".join(row_content_lines)

            chunks.append(full_chunk_text)
            ids.append(chunk_id)
            metadatas.append(
                {
                    "source": table_source_name(table_name),
                    "chunk_index": idx,
                    "document_title": header,
                    "table_name": table_name,
                    "record_id": str(row_id_val),
                }
            )

        return chunks, ids, metadatas
