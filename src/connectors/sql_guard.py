"""Read-only SQL guard: token-level validation of generated queries (sqlparse).

Defense in depth on top of the database-enforced read-only session in DatabaseConnector.execute_query:
single statement, SELECT/WITH only, no data/schema/session-modifying keywords, no file/network/sleep functions,
and table references limited to the allow-list.
"""

from typing import Any, List, Sequence, Set, Tuple

import sqlparse
from sqlparse import tokens as T

from src.core.logger import get_logger

logger = get_logger("SqlGuard")

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


def validate_read_only_query(query: str, allowed_tables: Sequence[str] = ()) -> Tuple[bool, str]:
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
    if allowed_tables:
        allowed = {_normalize_identifier(t) for t in allowed_tables}
        referenced_tables, cte_names = extract_table_references(clean_query)
        for tbl in sorted(referenced_tables):
            if tbl not in allowed and tbl not in cte_names:
                logger.warning(f"Unauthorized table access attempt: '{tbl}' in query: '{clean_query}'")
                return (
                    False,
                    f"Security Guard: Access to table '{tbl}' is not permitted.",
                )

    return True, ""
