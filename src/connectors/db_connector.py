"""Database-agnostic read-only connector (SQLAlchemy): schema discovery and guarded query execution."""

from typing import Any, Dict, List, Optional, Tuple

from src.connectors.sql_guard import validate_read_only_query
from src.core.config import (
    DATABASE_URL,
    DB_ALLOWED_TABLES,
    DB_MAX_ROWS,
    DB_QUERY_TIMEOUT_SECONDS,
)
from src.core.logger import get_logger

logger = get_logger("DatabaseConnector")


class DatabaseConnector:
    """SQLAlchemy-based universal, database-agnostic, and secure database connector.

    Manages relational databases (PostgreSQL, MySQL, SQLite, MSSQL, Oracle)
    through a unified interface with strict read-only security guards.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        allowed_tables: Optional[List[str]] = None,
        max_rows: int = DB_MAX_ROWS,
    ):
        self.database_url = database_url if database_url is not None else DATABASE_URL
        self.allowed_tables = allowed_tables if allowed_tables is not None else DB_ALLOWED_TABLES
        self.max_rows = max_rows
        self.engine = None
        self.is_connected = False
        self._last_error = None

        if self.database_url:
            self._init_engine()

    @property
    def dialect(self) -> str:
        """Return the database dialect name (e.g. 'sqlite', 'postgresql', 'mysql')."""
        if self.engine is not None:
            return self.engine.dialect.name
        if self.database_url:
            return self.database_url.split("://", 1)[0].split("+", 1)[0].lower()
        return "unknown"

    def _init_engine(self):
        """Initialize the SQLAlchemy engine with database-level read-only protections."""
        try:
            from sqlalchemy import create_engine, event

            # SQLite thread safety and path handling
            connect_args = {}
            if self.database_url.startswith("sqlite"):
                connect_args = {"check_same_thread": False}

            self.engine = create_engine(self.database_url, pool_pre_ping=True, connect_args=connect_args)

            if self.engine.dialect.name == "sqlite":

                @event.listens_for(self.engine, "connect")
                def _sqlite_read_only(dbapi_connection, _record):
                    # Rejects any write, ATTACH-ed database writes included, at the SQLite engine level
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA query_only = ON")
                    cursor.close()
            elif self.engine.dialect.name not in ("postgresql", "mysql", "mariadb"):
                logger.warning(
                    f"No session-level read-only enforcement for dialect '{self.engine.dialect.name}'. "
                    "Connect with a database account that only has SELECT privileges."
                )

            # Test connection
            with self.engine.connect():
                pass
            self.is_connected = True
            self._last_error = None
        except Exception as e:
            self.engine = None
            self.is_connected = False
            self._last_error = str(e)
            logger.error(f"Failed to connect to database: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """Test database connection, return dialect and accessible tables."""
        if not self.database_url:
            return {
                "status": "not_configured",
                "message": "Database URL (DATABASE_URL) is not configured.",
                "dialect": None,
                "tables": [],
            }

        if not self.is_connected or not self.engine:
            self._init_engine()

        if not self.is_connected:
            return {
                "status": "error",
                "message": f"Connection error: {self._last_error}",
                "dialect": None,
                "tables": [],
            }

        try:
            tables = self.get_tables()
            dialect_name = self.engine.dialect.name
            return {
                "status": "connected",
                "message": f"Successfully connected ({dialect_name.upper()}).",
                "dialect": dialect_name,
                "tables": tables,
                "table_count": len(tables),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Error querying tables: {e}",
                "dialect": self.engine.dialect.name if self.engine else None,
                "tables": [],
            }

    def get_tables(self) -> List[str]:
        """Return list of accessible table names (filtered by allowed_tables)."""
        if not self.is_connected or not self.engine:
            return []

        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        all_tables = inspector.get_table_names()

        # Exclude internal / system tables
        ignored_tables = {"sqlite_sequence"}
        tables = [t for t in all_tables if t not in ignored_tables]

        if self.allowed_tables:
            tables = [t for t in tables if t in self.allowed_tables]

        return sorted(tables)

    def get_table_overview(self, max_tables: int = 20, max_columns: int = 12) -> Dict[str, List[str]]:
        """Return {table: [column names]} for accessible tables; a compact schema for routing prompts."""
        if not self.is_connected or not self.engine:
            return {}

        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        return {
            table: [col["name"] for col in inspector.get_columns(table)][:max_columns]
            for table in self.get_tables()[:max_tables]
        }

    def get_schema_summary(self) -> str:
        """Generate schema summary (tables, columns, types) as text for LLM prompts."""
        if not self.is_connected or not self.engine:
            return "Database connection is not active."

        try:
            from sqlalchemy import inspect

            inspector = inspect(self.engine)
            tables = self.get_tables()

            if not tables:
                return "No accessible tables found."

            schema_lines = [f"# DATABASE SCHEMA (Dialect: {self.engine.dialect.name.upper()})"]

            for table in tables:
                columns = inspector.get_columns(table)
                pk_constraint = inspector.get_pk_constraint(table)
                pks = set(pk_constraint.get("constrained_columns", []) if pk_constraint else [])

                col_strs = []
                for col in columns:
                    col_name = col["name"]
                    col_type = str(col["type"])
                    is_pk = " [PK]" if col_name in pks else ""
                    col_strs.append(f"{col_name} ({col_type}{is_pk})")

                schema_lines.append(f"Table: {table}")
                schema_lines.append(f"  Columns: {', '.join(col_strs)}")

            return "\n".join(schema_lines)
        except Exception as e:
            return f"Error extracting schema: {e}"

    def _validate_sql_safety(self, query: str) -> Tuple[bool, str]:
        """(is_safe, error_message) for a query under this connector's table allow-list."""
        return validate_read_only_query(query, self.allowed_tables)

    def _apply_read_only_session(self, conn) -> None:
        """Force the current transaction to be read-only and bounded in time where the dialect supports it."""
        dialect = self.engine.dialect.name
        timeout_ms = max(1, DB_QUERY_TIMEOUT_SECONDS) * 1000
        if dialect == "postgresql":
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        elif dialect in ("mysql", "mariadb"):
            # Session scope: DDL implicitly commits, which would end a transaction-scoped read-only mode
            conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            try:
                if dialect == "mysql":
                    conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}")
                else:
                    conn.exec_driver_sql(f"SET SESSION max_statement_time = {int(timeout_ms / 1000)}")
            except Exception as e:
                logger.debug(f"Could not apply query timeout: {e}")

    def execute_query(self, query: str) -> Dict[str, Any]:
        """Execute SQL query subject to strict read-only security guards.

        Security Rules:
        1. Only a single 'SELECT' or 'WITH ... SELECT' statement is permitted.
        2. Data/schema modifying keywords and dangerous server functions are blocked (token-level analysis).
        3. Table references are checked against allowed_tables (FROM lists, JOINs, subqueries).
        4. The query runs inside a database-enforced read-only transaction (SQLite query_only,
           PostgreSQL/MySQL read-only transactions) with a statement timeout.
        5. Result rows are capped at max_rows.
        """
        if not self.is_connected or not self.engine:
            return {
                "status": "error",
                "message": "Database connection is not active.",
                "columns": [],
                "rows": [],
            }

        clean_query = query.strip().rstrip(";").strip()

        # Validate SQL safety
        is_safe, error_msg = self._validate_sql_safety(clean_query)
        if not is_safe:
            return {"status": "error", "message": error_msg, "columns": [], "rows": []}

        try:
            from sqlalchemy import text

            with self.engine.connect() as conn:
                self._apply_read_only_session(conn)
                result = conn.execute(text(clean_query))
                columns = list(result.keys()) if result.returns_rows else []
                raw_rows = result.fetchmany(self.max_rows) if result.returns_rows else []
                conn.rollback()

                # Convert to JSON serializable dictionaries
                formatted_rows = []
                for row in raw_rows:
                    row_dict = {}
                    for col, val in zip(columns, row):
                        if val is None:
                            row_dict[col] = None
                        elif isinstance(val, (int, float, bool, str)):
                            row_dict[col] = val
                        else:
                            row_dict[col] = str(val)
                    formatted_rows.append(row_dict)

                return {
                    "status": "success",
                    "columns": columns,
                    "rows": formatted_rows,
                    "row_count": len(formatted_rows),
                    "query": clean_query,
                }
        except Exception as e:
            logger.warning(f"Query execution failed: {e}")
            return {
                "status": "error",
                "message": f"Error executing query: {type(e).__name__}",
                "columns": [],
                "rows": [],
            }
