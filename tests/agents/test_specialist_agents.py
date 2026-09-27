"""Behavior of the built-in specialists: doc_agent's Self-RAG guard, db_agent, and supervisor routing."""

import unittest
from unittest.mock import MagicMock

from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.grading import is_grade_passed
from src.agent.prompts import (
    FALLBACK_RESPONSE,
    SYSTEM_PROMPT_GRADER,
    SYSTEM_PROMPT_REFINE,
)


def scripted_chat_model(generate: str, grades: list, refined: str = "refined answer") -> MagicMock:
    """Chat model that answers by prompt type: grader -> next grade, refine -> refined, otherwise generate."""
    grade_iter = iter(grades)

    def invoke(messages):
        system = messages[0].content
        # startswith: agents append a response-language instruction to some system prompts
        if system.startswith(SYSTEM_PROMPT_GRADER):
            return MagicMock(content=next(grade_iter))
        if system.startswith(SYSTEM_PROMPT_REFINE):
            return MagicMock(content=refined)
        return MagicMock(content=generate)

    chat = MagicMock()
    chat.invoke.side_effect = invoke
    return chat


class TestDocAgentSelfRag(unittest.TestCase):
    def _agent(self, chat):
        engine = MagicMock()
        engine.search.return_value = {
            "context": "Annual leave is 20 days.",
            "sources": [{"source": "hr.txt"}],
        }
        return DocumentRagAgent(chat_model=chat, rag_engine=engine)

    def test_grounded_answer_passes(self):
        out = self._agent(scripted_chat_model("20 days.", ["yes"])).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")
        self.assertFalse(out["is_refined"])
        self.assertEqual(out["hallucination_grade"], "yes")

    def test_ungrounded_answer_is_refined(self):
        chat = scripted_chat_model("20 days and free cars.", ["no", "yes"], refined="20 days.")
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")
        self.assertTrue(out["is_refined"])

    def test_unverifiable_answer_falls_back(self):
        chat = scripted_chat_model("Made up.", ["no", "no"], refined="Still made up.")
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], FALLBACK_RESPONSE)

    def test_grader_failure_fails_closed(self):
        chat = MagicMock()
        chat.invoke.side_effect = [
            MagicMock(content="Answer"),
            RuntimeError("down"),
            MagicMock(content="Answer"),
            RuntimeError("down"),
        ]
        out = self._agent(chat).execute({"question": "Q?"})
        self.assertEqual(out["final_answer"], FALLBACK_RESPONSE)

    def test_grade_parsing(self):
        self.assertTrue(is_grade_passed("yes"))
        self.assertTrue(is_grade_passed("Evet, belgelerle tutarlı"))
        self.assertFalse(is_grade_passed("no, not yes"))
        self.assertFalse(is_grade_passed(""))


class TestDbAgent(unittest.TestCase):
    def _connector(self, query_result):
        connector = MagicMock()
        connector.is_connected = True
        connector.dialect = "sqlite"
        connector.get_schema_summary.return_value = "Table: urunler"
        connector.execute_query.return_value = query_result
        return connector

    def test_guard_error_stays_in_the_trace(self):
        connector = self._connector(
            {
                "status": "error",
                "message": "Security Guard: nope",
                "columns": [],
                "rows": [],
            }
        )
        chat = MagicMock()
        chat.invoke.return_value = MagicMock(content="SELECT * FROM secret")
        out = DatabaseAgent(chat_model=chat, db_connector=connector).execute({"question": "q"})
        # Database errors can reveal schema details: users get a generic message, the trace keeps the cause
        self.assertNotIn("Security Guard: nope", out["final_answer"])
        self.assertEqual(out["agent_trace"][-1]["error"], "Security Guard: nope")
        self.assertEqual(out["agent_trace"][-1]["status"], "rejected")

    def test_row_count_and_first_statement(self):
        rows = [{"id": 1}, {"id": 2}]
        connector = self._connector({"status": "success", "columns": ["id"], "rows": rows, "row_count": 2})
        chat = MagicMock()
        chat.invoke.side_effect = [
            MagicMock(content="```sql\nSELECT id FROM t WHERE name = 'a;b'; DROP TABLE t\n```"),
            MagicMock(content="Two rows."),
        ]
        out = DatabaseAgent(chat_model=chat, db_connector=connector).execute({"question": "q"})
        connector.execute_query.assert_called_once_with("SELECT id FROM t WHERE name = 'a;b'")
        self.assertEqual(out["agent_trace"][-1]["row_count"], 2)
        explain_prompt = chat.invoke.call_args_list[1][0][0][1].content
        self.assertIn("Row Count: 2", explain_prompt)

    def test_generation_error_does_not_leak(self):
        chat = MagicMock()
        chat.invoke.side_effect = RuntimeError("internal host 10.0.0.5")
        out = DatabaseAgent(chat_model=chat, db_connector=self._connector({})).execute({"question": "q"})
        self.assertNotIn("10.0.0.5", out["final_answer"])


class TestSupervisorRouting(unittest.TestCase):
    def setUp(self):
        self.chat = MagicMock()
        self.chat.invoke.return_value = MagicMock(content='{"agent": "finish", "reason": "r", "direct_response": "ok"}')
        self.supervisor = SupervisorAgent(chat_model=self.chat, registry=AgentRegistry())

    def test_pure_greeting_short_circuits(self):
        for greeting in ("Hello", "Merhaba, nasılsın?", "hi there", "iyi günler"):
            out = self.supervisor.route({"question": greeting})
            self.assertEqual(out["agent_trace"][-1]["action"], "direct_greeting", greeting)
        self.chat.invoke.assert_not_called()

    def test_greeting_with_request_is_routed(self):
        out = self.supervisor.route({"question": "hi, list sales"})
        self.assertEqual(out["agent_trace"][-1]["action"], "intent_routing")
        self.chat.invoke.assert_called_once()

    def test_routing_prompt_includes_history(self):
        history = [{"question": "Top product by sales?", "answer": "X", "agent": "db_agent"}]
        self.supervisor.route({"question": "And last month?", "chat_history": history})
        human = self.chat.invoke.call_args[0][0][1].content
        self.assertIn("Top product by sales?", human)
        self.assertIn("db_agent", human)
