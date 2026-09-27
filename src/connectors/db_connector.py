import os
import sqlite3
from typing import Optional, Dict, Any, List, Set, Tuple

import sqlparse
from sqlparse import tokens as T

from src.core.config import (
    DATABASE_URL,
    DB_ALLOWED_TABLES,
    DB_MAX_ROWS,
    DB_QUERY_TIMEOUT_SECONDS,
    SAMPLE_DB_PATH,
)
from src.core.logger import get_logger

logger = get_logger("DatabaseConnector")

# Statement keywords that can modify data, schema, session state, or the filesystem.
FORBIDDEN_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "CREATE",
        "GRANT",
        "REVOKE",
        "MERGE",
        "UPSERT",
        "INTO",
        "ATTACH",
        "DETACH",
        "PRAGMA",
        "CALL",
        "COPY",
        "VACUUM",
        "LOCK",
        "SET",
        "DECLARE",
        "LOAD",
        "HANDLER",
        "SHUTDOWN",
        "KILL",
        "RENAME",
        "REINDEX",
        "OUTFILE",
        "DUMPFILE",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "USE",
    }
)

# Functions that read/write files, reach the network, stall the server, or alter server state.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "set_config",
        "lo_import",
        "lo_export",
        "lo_get",
        "lo_put",
        "lo_from_bytea",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "load_extension",
        "load_file",
        "sleep",
        "benchmark",
        "xp_cmdshell",
        "xp_dirtree",
        "openrowset",
        "opendatasource",
        "openquery",
        "readfile",
        "writefile",
        "fts3_tokenizer",
    }
)
FORBIDDEN_FUNCTION_PREFIXES = ("dbms_", "utl_", "sys_exec", "sys_eval")

# Keywords ending a FROM-list (after which commas no longer separate tables)
_FROM_LIST_TERMINATORS = frozenset(
    {
        "WHERE",
        "GROUP BY",
        "ORDER BY",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "FETCH",
        "UNION",
        "UNION ALL",
        "INTERSECT",
        "EXCEPT",
        "WINDOW",
        "SELECT",
        "QUALIFY",
    }
)
# Join conditions end the current table reference but a following comma still adds tables
_JOIN_CONDITION_KEYWORDS = frozenset({"ON", "USING"})
_TABLE_PREFIX_KEYWORDS = frozenset({"LATERAL", "ONLY"})


def _significant_tokens(statement) -> List[Any]:
    """Flatten a parsed statement, dropping whitespace and comments."""
    return [tok for tok in statement.flatten() if not tok.is_whitespace and tok.ttype not in T.Comment]


def _normalize_identifier(value: str) -> str:
    return value.strip().strip('"`[]').lower()


def extract_table_references(query: str) -> Tuple[Set[str], Set[str]]:
    """Return (referenced_tables, cte_names) for a SELECT statement using sqlparse tokens.

    Handles comma-separated FROM lists, JOIN variants, schema-qualified and quoted names,
    and nested subqueries. Table names are lower-cased and unquoted; for schema-qualified
    references the last component (the table) is returned.
    """
    tables: Set[str] = set()
    cte_names: Set[str] = set()
    for statement in sqlparse.parse(query):
        toks = _significant_tokens(statement)
        depth = 0
        from_depths: List[int] = []  # paren depths at which a FROM-list is currently open
        expecting_table = False
        i = 0
        while i < len(toks):
            tok = toks[i]
            val = tok.normalized.upper() if tok.ttype in T.Keyword else tok.value

            # CTE definition: <name> AS (
            if (
                i + 2 < len(toks)
                and (tok.ttype in T.Name or tok.ttype in T.Literal.String.Symbol)
                and toks[i + 1].ttype in T.Keyword
                and toks[i + 1].normalized == "AS"
                and toks[i + 2].value == "("
            ):
                cte_names.add(_normalize_identifier(tok.value))

            if tok.ttype in T.Punctuation and tok.value == "(":
                depth += 1
                expecting_table = False
                i += 1
                continue
            if tok.ttype in T.Punctuation and tok.value == ")":
                depth -= 1
                while from_depths and from_depths[-1] > depth:
                    from_depths.pop()
                i += 1
                continue

            if tok.ttype in T.Keyword:
                if val == "FROM" or val.endswith("JOIN"):
                    expecting_table = True
                    while from_depths and from_depths[-1] >= depth:
                        from_depths.pop()
                    from_depths.append(depth)
                    i += 1
                    continue
                if val in _JOIN_CONDITION_KEYWORDS:
                    expecting_table = False
                    i += 1
                    continue
                if val in _FROM_LIST_TERMINATORS:
                    while from_depths and from_depths[-1] >= depth:
                        from_depths.pop()
                    expecting_table = False
                    i += 1
                    continue
                if expecting_table and val in _TABLE_PREFIX_KEYWORDS:
                    i += 1
                    continue
            if tok.ttype in T.DML and val.upper() == "SELECT":
                while from_depths and from_depths[-1] >= depth:
                    from_depths.pop()
                expecting_table = False

            if tok.ttype in T.Punctuation and tok.value == ",":
                if from_depths and from_depths[-1] == depth:
                    expecting_table = True
                i += 1
                continue

            if expecting_table:
                if tok.ttype in T.Name or tok.ttype in T.Literal.String.Symbol or tok.ttype in T.Keyword:
                    # Collect dotted name: schema.table or db.schema.table
                    name = tok.value
                    j = i + 1
                    while (
                        j + 1 < len(toks)
                        and toks[j].value == "."
                        and (
                            toks[j + 1].ttype in T.Name
                            or toks[j + 1].ttype in T.Literal.String.Symbol
                            or toks[j + 1].ttype in T.Keyword
                        )
                    ):
                        name = toks[j + 1].value
                        j += 2
                    # A name followed by "(" is a table-valued function, not a table
                    if not (j < len(toks) and toks[j].value == "("):
                        tables.add(_normalize_identifier(name))
                    expecting_table = False
                    i = j
                    continue
                expecting_table = False
            i += 1
    return tables, cte_names


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

    def _validate_sql_safety(self, query: str) -> tuple[bool, str]:
        """Validate that a query is a single, read-only SELECT using sqlparse token analysis.

        This is defense in depth on top of the database-level read-only session applied in
        execute_query; production deployments should additionally use a SELECT-only account.
        Returns (is_safe, error_message). If is_safe is True, error_message is empty.
        """
        clean_query = query.strip().rstrip(";").strip()
        if not clean_query:
            return False, "Invalid Query: Empty query."

        # 1. Exactly one statement
        statements = [stmt for stmt in sqlparse.split(clean_query) if stmt.strip().rstrip(";").strip()]
        if len(statements) != 1:
            return False, "Security Guard: Only a single SQL statement is allowed."

        parsed = sqlparse.parse(clean_query)
        if not parsed:
            return False, "Invalid Query: Could not parse SQL statement."
        statement = parsed[0]
        tokens = _significant_tokens(statement)
        if not tokens:
            return False, "Invalid Query: Could not parse SQL statement."

        # 2. Forbidden keywords and functions (string literals are ignored, so values like 'Deleted' are fine)
        for idx, tok in enumerate(tokens):
            if tok.ttype in T.Literal.String and tok.ttype not in T.Literal.String.Symbol:
                continue
            upper = tok.normalized.upper() if tok.ttype in T.Keyword else tok.value.upper()
            for word in upper.split():
                if word in FORBIDDEN_KEYWORDS and (tok.ttype in T.Keyword or tok.ttype in T.Name):
                    return (
                        False,
                        f"Security Guard: Forbidden keyword '{word}' detected. Only read-only (SELECT) queries are allowed.",
                    )
            is_call = idx + 1 < len(tokens) and tokens[idx + 1].value == "("
            if is_call:
                func = _normalize_identifier(tok.value)
                if func in FORBIDDEN_FUNCTIONS or func.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                    return False, f"Security Guard: Function '{func}' is not permitted."

        # 3. Must start with SELECT or WITH
        first = tokens[0]
        if first.normalized.upper() not in ("SELECT", "WITH"):
            return False, "Invalid Query: Query must start with 'SELECT' or 'WITH'."

        stmt_type = statement.get_type()
        if stmt_type and stmt_type.upper() not in ("SELECT", "UNKNOWN"):
            return (
                False,
                f"Security Guard: Statement type '{stmt_type}' is not permitted. Only SELECT is allowed.",
            )

        # 4. Table Access Restriction (if allowed_tables is specified)
        if self.allowed_tables:
            allowed = {_normalize_identifier(t) for t in self.allowed_tables}
            referenced_tables, cte_names = extract_table_references(clean_query)
            for tbl in sorted(referenced_tables):
                if tbl not in allowed and tbl not in cte_names:
                    logger.warning(f"Unauthorized table access attempt: '{tbl}' in query: '{clean_query}'")
                    return (
                        False,
                        f"Security Guard: Access to table '{tbl}' is not permitted.",
                    )

        return True, ""

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


def create_sample_sqlite_db(db_path: Optional[str] = None) -> str:
    """Generate sample enterprise SQLite database for instant zero-config testing."""
    target_path = db_path or SAMPLE_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    conn = sqlite3.connect(target_path)
    cursor = conn.cursor()

    # 1. Products Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS urunler (
        urun_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        urun_adi TEXT NOT NULL,
        kategori TEXT NOT NULL,
        birim_fiyat REAL NOT NULL,
        stok_adedi INTEGER NOT NULL
    );
    """)

    # 2. Sales Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS satislar (
        satis_id INTEGER PRIMARY KEY AUTOINCREMENT,
        siparis_no TEXT NOT NULL,
        musteri_adi TEXT NOT NULL,
        urun_id INTEGER,
        adet INTEGER NOT NULL,
        toplam_tutar REAL NOT NULL,
        bolge TEXT NOT NULL,
        tarih TEXT NOT NULL,
        FOREIGN KEY (urun_id) REFERENCES urunler(urun_id)
    );
    """)

    # 3. Support Requests Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS destek_talepleri (
        talep_id INTEGER PRIMARY KEY AUTOINCREMENT,
        talep_kodu TEXT NOT NULL,
        musteri_adi TEXT NOT NULL,
        konu TEXT NOT NULL,
        detay TEXT NOT NULL,
        cozum TEXT NOT NULL,
        durum TEXT NOT NULL
    );
    """)

    # Populate initial sample records if empty
    cursor.execute("SELECT COUNT(*) FROM urunler;")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            """
        INSERT INTO urunler (sku, urun_adi, kategori, birim_fiyat, stok_adedi) VALUES (?, ?, ?, ?, ?);
        """,
            [
                ("NT-SRV-01", "NovaTech Enterprise Server X1", "Hardware", 85000.0, 14),
                ("NT-LPT-02", "NovaTech ProBook 15 G3", "Computer", 38500.0, 45),
                ("NT-SEC-03", "NovaShield Enterprise Firewall", "Security", 62000.0, 8),
                (
                    "NT-SFT-04",
                    "NovaERP Cloud License (Annual)",
                    "Software",
                    120000.0,
                    100,
                ),
                ("NT-MON-05", "NovaView 27-inch 4K Monitor", "Accessory", 9400.0, 60),
            ],
        )

        cursor.executemany(
            """
        INSERT INTO satislar (siparis_no, musteri_adi, urun_id, adet, toplam_tutar, bolge, tarih) VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
            [
                (
                    "ORD-2026-001",
                    "Anadolu Logistics Corp.",
                    1,
                    2,
                    170000.0,
                    "Marmara",
                    "2026-01-15",
                ),
                (
                    "ORD-2026-002",
                    "Capital Health Group",
                    2,
                    5,
                    192500.0,
                    "Central",
                    "2026-01-18",
                ),
                (
                    "ORD-2026-003",
                    "Aegean IT Systems",
                    3,
                    1,
                    62000.0,
                    "Aegean",
                    "2026-02-02",
                ),
                (
                    "ORD-2026-004",
                    "Mediterranean Retail Ltd.",
                    4,
                    1,
                    120000.0,
                    "Mediterranean",
                    "2026-02-14",
                ),
                (
                    "ORD-2026-005",
                    "Anadolu Logistics Corp.",
                    5,
                    4,
                    37600.0,
                    "Marmara",
                    "2026-03-01",
                ),
            ],
        )

        cursor.executemany(
            """
        INSERT INTO destek_talepleri (talep_kodu, musteri_adi, konu, detay, cozum, durum) VALUES (?, ?, ?, ?, ?, ?);
        """,
            [
                (
                    "SR-2026-101",
                    "Anadolu Logistics Corp.",
                    "Server BIOS Update",
                    "IPMI disconnected after Enterprise Server X1 reboot.",
                    "Applied IPMI firmware 2.14 patch and reset static IP.",
                    "Resolved",
                ),
                (
                    "SR-2026-102",
                    "Capital Health Group",
                    "ERP License Activation Error",
                    "Users receiving 'License Limit Exceeded' warning.",
                    "Terminated stale sessions on license server and cleaned connection pool.",
                    "Resolved",
                ),
                (
                    "SR-2026-103",
                    "Aegean IT Systems",
                    "Firewall VPN Setup",
                    "IKEv2 key mismatch when establishing IPsec tunnel.",
                    "Synchronized Phase-1 and Phase-2 encryption algorithms to AES-256.",
                    "Resolved",
                ),
            ],
        )

    conn.commit()
    conn.close()
    return target_path
