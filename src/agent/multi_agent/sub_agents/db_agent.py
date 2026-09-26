import time
import json
import re

import sqlparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.connectors.db_connector import DatabaseConnector
from src.core.logger import get_logger

logger = get_logger("MultiAgent.DbAgent")

SQL_GENERATOR_SYSTEM_PROMPT = """You are an expert SQL analyst and database specialist.
Your task is to generate a single safe, read-only SQL query to run against a relational database to answer the user's question.

Available Database Schema:
{schema_summary}

SECURITY AND EXECUTION RULES:
1. ONLY generate 'SELECT' or 'WITH ... SELECT' queries.
2. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or any DDL/DML statements.
3. Only query tables listed in the schema above.
4. Do NOT wrap output in markdown code blocks (```sql ... ```) or add explanations. Output ONLY the raw executable SQL query.
5. Use LIMIT where appropriate to avoid unbounded result sets.
"""

SQL_EXPLAINER_SYSTEM_PROMPT = """You are a professional business intelligence and data analyst assistant.
The user's question and the SQL query results returned from the database are provided below.
Explain and summarize the results for the user clearly, professionally, and accurately, utilizing Markdown tables or bullet points when appropriate.
If the result set is empty, politely indicate that no matching records were found in the database.
"""


@register_agent
class DatabaseAgent(BaseSubAgent):
    """Specialist sub-agent for querying relational databases with strict AST read-only guards."""

    name: str = "db_agent"
    display_name: str = "SQL & Database Analyst"
    description: str = (
        "Used for querying structured relational database tables (products, inventory, sales, "
        "orders, tickets, etc.) using secure read-only SQL and reporting structured data insights."
    )

    def __init__(self, chat_model=None, db_connector: Optional[DatabaseConnector] = None):
        super().__init__(chat_model=chat_model)
        self._db_connector = db_connector

    def _get_connector(self) -> DatabaseConnector:
        if self._db_connector is None:
            from src.api.state import get_db_connector

            self._db_connector = get_db_connector()
        return self._db_connector

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate, validate, and execute read-only SQL queries to answer operational data questions."""
        start_time = time.time()
        question = state.get("question", "").strip()
        connector = self._get_connector()

        if not connector.is_connected:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = "Database connection is currently not active or not configured."
            trace_entry = {
                "agent": self.name,
                "display_name": self.display_name,
                "action": "db_connection_check",
                "duration_ms": duration_ms,
                "status": "not_connected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "final_answer": msg,
                "sources": [],
                "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
            }

        # 1. Fetch available schema
        schema_summary = connector.get_schema_summary()

        # 2. Generate SQL via LLM (recent turns help resolve follow-up questions)
        prompt = SQL_GENERATOR_SYSTEM_PROMPT.format(schema_summary=schema_summary)
        history_lines = [
            f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')}"
            for turn in state.get("chat_history", [])[-3:]
            if turn.get("question") and turn.get("answer")
        ]
        human_content = question
        if history_lines:
            human_content = "Recent conversation:\n" + "\n".join(history_lines) + f"\n\nCurrent question: {question}"
        try:
            sql_response = self.chat_model.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=human_content),
                ]
            )
            generated_sql = sql_response.content.strip()

            # Clean markdown code blocks if present
            sql_cleaned = re.sub(r"^```(?:sql)?\s*", "", generated_sql, flags=re.IGNORECASE)
            sql_cleaned = re.sub(r"\s*```$", "", sql_cleaned).strip()
            # Keep only the first statement (sqlparse respects semicolons inside string literals)
            statements = [stmt.strip() for stmt in sqlparse.split(sql_cleaned) if stmt.strip()]
            if statements:
                sql_cleaned = statements[0].rstrip(";").strip()

            logger.info(f"[{self.name}] Generated SQL: '{sql_cleaned}'")
        except Exception as e:
            logger.error(f"[{self.name}] Error during SQL generation: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "final_answer": "An error occurred while generating the database query. Please try again or rephrase your question.",
                "sources": [],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": self.name,
                        "action": "sql_generation",
                        "status": "error",
                        "duration_ms": duration_ms,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        # 3. Execute safe query via DatabaseConnector AST security guards
        query_result = connector.execute_query(sql_cleaned)

        if query_result.get("status") == "error":
            duration_ms = int((time.time() - start_time) * 1000)
            err_msg = query_result.get("message", "Unknown database error")
            return {
                "final_answer": f"Database query could not be executed due to security or syntax constraints:\n`{err_msg}`",
                "sources": [],
                "agent_trace": list(state.get("agent_trace", []))
                + [
                    {
                        "agent": self.name,
                        "action": "sql_execution",
                        "sql": sql_cleaned,
                        "status": "rejected",
                        "error": err_msg,
                        "duration_ms": duration_ms,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])
        count = query_result.get("row_count", len(rows))

        # 4. Synthesize tabular result into user-friendly explanation
        explain_prompt = (
            f"User Question: {question}\n\n"
            f"Executed SQL: {sql_cleaned}\n"
            f"Returned Columns: {', '.join(columns)}\n"
            f"Row Count: {count}\n"
            f"Data (JSON):\n{json.dumps(rows[:30], ensure_ascii=False, indent=2)}"
        )

        try:
            summary_response = self.chat_model.invoke(
                [
                    SystemMessage(content=SQL_EXPLAINER_SYSTEM_PROMPT),
                    HumanMessage(content=explain_prompt),
                ]
            )
            answer = summary_response.content.strip()
        except Exception as e:
            logger.error(f"[{self.name}] Error synthesizing SQL results: {e}")
            answer = f"Query executed successfully ({count} records found):\n\n```json\n{json.dumps(rows[:10], ensure_ascii=False, indent=2)}\n```"

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "sql_query_and_explain",
            "sql": sql_cleaned,
            "row_count": count,
            "duration_ms": duration_ms,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Format sources as database table metadata
        sources = [
            {
                "source": f"Database: {connector.dialect}",
                "chunk_index": 0,
                "content": f"Executed SQL: {sql_cleaned} ({count} rows returned)",
            }
        ]

        return {
            "final_answer": answer,
            "sources": sources,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
