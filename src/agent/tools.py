import json
from typing import Optional

from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from src.connectors.db_connector import DatabaseConnector

# ──────────────────────────── DATABASE TOOLS ────────────────────────────

# Resolved lazily to the application's shared connector (tests may assign a stub directly)
db_connector: Optional[DatabaseConnector] = None


def _get_connector() -> DatabaseConnector:
    global db_connector
    if db_connector is None:
        from src.api.state import get_db_connector

        db_connector = get_db_connector()
    return db_connector


@tool(
    "sql_db_schema",
    description="Lists accessible tables and columns in the enterprise database. Use to inspect available tables and their schemas.",
)
def sql_db_schema(dummy: str = "") -> str:
    """Return the schema summary of the database."""
    connector = _get_connector()
    if not connector.is_connected:
        return "Notice: Database connection is not configured or inactive."
    return connector.get_schema_summary()


@tool(
    "sql_db_query",
    description="Executes a safe, read-only SQL SELECT query on the database. Use to query sales, products, inventory, orders, and numeric records.",
)
def sql_db_query(query: str) -> str:
    """Execute a safe, read-only SQL query against the database."""
    connector = _get_connector()
    if not connector.is_connected:
        return "Error: Database connection is not active."

    res = connector.execute_query(query)
    if res["status"] != "success":
        return f"Error: {res.get('message', 'Query failed.')}"

    rows = res.get("rows", [])
    if not rows:
        return "Query executed successfully, but no matching rows were found."

    return json.dumps(rows, ensure_ascii=False, indent=2)


all_tools = [sql_db_schema, sql_db_query]
tool_schema = [convert_to_openai_tool(t) for t in all_tools]
tools_by_name = {t.name: t for t in all_tools}
