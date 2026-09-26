import unittest
import json
from unittest.mock import patch
from src.agent.tools import (
    sql_db_schema,
    sql_db_query,
    all_tools,
    tools_by_name,
    tool_schema,
)


class TestAgentTools(unittest.TestCase):
    """Unit tests for agent tools registry and database tools."""

    def test_tool_registry_does_not_contain_calculator(self):
        """Verify calculator tool is removed and only DB tools are registered."""
        self.assertNotIn("calculator", tools_by_name)
        self.assertIn("sql_db_schema", tools_by_name)
        self.assertIn("sql_db_query", tools_by_name)
        self.assertEqual(len(all_tools), 2)

    def test_tool_schemas_generated(self):
        """Verify schemas are generated for function calling."""
        self.assertEqual(len(tool_schema), 2)
        tool_names = [s["function"]["name"] if "function" in s else s.get("name") for s in tool_schema]
        self.assertIn("sql_db_schema", tool_names)
        self.assertIn("sql_db_query", tool_names)

    @patch("src.agent.tools.db_connector")
    def test_sql_db_schema_disconnected(self, mock_db):
        mock_db.is_connected = False
        res = sql_db_schema.invoke({})
        self.assertIn("inactive", res.lower())

    @patch("src.agent.tools.db_connector")
    def test_sql_db_schema_connected(self, mock_db):
        mock_db.is_connected = True
        mock_db.get_schema_summary.return_value = "Table: users (id INT, name TEXT)"
        res = sql_db_schema.invoke({})
        self.assertIn("users", res)

    @patch("src.agent.tools.db_connector")
    def test_sql_db_query_disconnected(self, mock_db):
        mock_db.is_connected = False
        res = sql_db_query.invoke({"query": "SELECT * FROM users"})
        self.assertIn("error", res.lower())

    @patch("src.agent.tools.db_connector")
    def test_sql_db_query_success(self, mock_db):
        mock_db.is_connected = True
        mock_db.execute_query.return_value = {
            "status": "success",
            "rows": [{"id": 1, "name": "Alper"}],
            "count": 1,
        }
        res = sql_db_query.invoke({"query": "SELECT * FROM users"})
        parsed = json.loads(res)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "Alper")

    @patch("src.agent.tools.db_connector")
    def test_sql_db_query_empty_result(self, mock_db):
        mock_db.is_connected = True
        mock_db.execute_query.return_value = {
            "status": "success",
            "rows": [],
            "count": 0,
        }
        res = sql_db_query.invoke({"query": "SELECT * FROM users WHERE id = 999"})
        self.assertIn("no matching rows", res.lower())


if __name__ == "__main__":
    unittest.main()
