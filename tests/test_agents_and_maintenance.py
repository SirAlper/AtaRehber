"""Tests for sub-agent behavior (Self-RAG, SQL agent), supervisor routing, and maintenance operations."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.nodes import AgentNodes, is_grade_passed
from src.agent.prompts import (
    FALLBACK_RESPONSE,
    SYSTEM_PROMPT_GRADER,
    SYSTEM_PROMPT_REFINE,
)
from src.rag.rag_engine import distance_to_similarity


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
        self.assertEqual(
            AgentNodes.decide_hallucinate({"hallucination_grade": "no, not yes", "retry_count": 0}),
            "refine",
        )


class TestDbAgent(unittest.TestCase):
    def _connector(self, query_result):
        connector = MagicMock()
        connector.is_connected = True
        connector.dialect = "sqlite"
        connector.get_schema_summary.return_value = "Table: urunler"
        connector.execute_query.return_value = query_result
        return connector

    def test_guard_error_message_is_reported(self):
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
        self.assertIn("Security Guard: nope", out["final_answer"])

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


class TestSessionCleanup(unittest.TestCase):
    def test_only_expired_threads_removed(self):
        from langgraph.checkpoint.base import empty_checkpoint
        from langgraph.checkpoint.sqlite import SqliteSaver
        from src.agent.multi_agent.sessions import cleanup_expired_sessions

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        db_path = os.path.join(tmp, "conv.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        for thread_id, age_days in (("old_thread", 45), ("fresh_thread", 1)):
            checkpoint = empty_checkpoint()
            checkpoint["ts"] = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
            saver.put(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                checkpoint,
                {},
                {},
            )
        conn.close()

        deleted = cleanup_expired_sessions(max_age_days=30, db_path=db_path)
        self.assertEqual(deleted, 1)

        conn = sqlite3.connect(db_path)
        remaining = {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
        conn.close()
        self.assertEqual(remaining, {"fresh_thread"})

    def test_missing_database_is_noop(self):
        from src.agent.multi_agent.sessions import cleanup_expired_sessions

        self.assertEqual(
            cleanup_expired_sessions(db_path=os.path.join(tempfile.gettempdir(), "nope_does_not_exist.db")),
            0,
        )


class TestVectorDbRestore(unittest.TestCase):
    def setUp(self):
        import src.api.state as state

        self.state = state
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vdb = os.path.join(self.tmp, "vector_db")
        self.backups = os.path.join(self.tmp, "backups")
        os.makedirs(self.vdb)
        with open(os.path.join(self.vdb, "marker.txt"), "w") as f:
            f.write("live")
        for name, value in (
            ("VECTOR_DB_PATH", self.vdb),
            ("BACKUP_DIR", self.backups),
            ("PENDING_RESTORE_PATH", os.path.join(self.backups, ".restore_pending")),
            ("rag_engine", None),
        ):
            patcher = patch.object(state, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_restore_is_staged_then_applied_on_startup(self):
        backup_path = self.state.backup_vector_db()
        with open(os.path.join(self.vdb, "marker.txt"), "w") as f:
            f.write("changed after backup")

        self.assertTrue(self.state.restore_vector_db(backup_path))
        # Live database untouched until restart
        with open(os.path.join(self.vdb, "marker.txt")) as f:
            self.assertEqual(f.read(), "changed after backup")

        self.assertTrue(self.state.apply_pending_restore())
        with open(os.path.join(self.vdb, "marker.txt")) as f:
            self.assertEqual(f.read(), "live")
        pre_restore = [n for n in os.listdir(self.backups) if n.startswith("pre_restore_")]
        self.assertEqual(len(pre_restore), 1)
        with open(os.path.join(self.backups, pre_restore[0], "marker.txt")) as f:
            self.assertEqual(f.read(), "changed after backup")
        self.assertFalse(self.state.apply_pending_restore())

    def test_restore_keeps_vector_db_directory_in_place(self):
        """In Docker the vector_db directory is a bind-mount point and must never be renamed or removed."""
        backup_path = self.state.backup_vector_db()
        original_inode = os.stat(self.vdb).st_ino
        self.state.restore_vector_db(backup_path)
        with patch("src.api.state.shutil.move", wraps=shutil.move) as move:
            self.assertTrue(self.state.apply_pending_restore())
        moved_sources = [os.path.normpath(call.args[0]) for call in move.call_args_list]
        self.assertNotIn(os.path.normpath(self.vdb), moved_sources)
        self.assertEqual(os.stat(self.vdb).st_ino, original_inode)

    def test_backup_name_validation(self):
        self.assertTrue(self.state.is_valid_backup_name("vector_db_backup_20260101_000000"))
        for bad in (
            "../vector_db",
            "vector_db_backup_../../etc",
            "other_dir",
            "",
            "a/vector_db_backup_1",
        ):
            self.assertFalse(self.state.is_valid_backup_name(bad), bad)


class TestFirstRunSampleDatabase(unittest.TestCase):
    def test_connector_uses_sample_db_created_after_config_load(self):
        """On a fresh install the sample DB is created at startup, after DATABASE_URL was resolved as empty."""
        import src.api.state as state
        from src.connectors.db_connector import create_sample_sqlite_db

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        sample_path = os.path.join(tmp, "sample_enterprise.db")
        create_sample_sqlite_db(sample_path)

        with (
            patch.object(state, "DATABASE_URL", ""),
            patch.object(state, "SAMPLE_DB_PATH", sample_path),
            patch.object(state, "DEFAULT_SQLITE_URL", f"sqlite:///{sample_path}"),
            patch.object(state, "db_connector", None),
        ):
            connector = state.get_db_connector()
            try:
                self.assertTrue(connector.is_connected)
                self.assertIn("urunler", connector.get_tables())
            finally:
                connector.engine.dispose()


class TestSimilarityConversion(unittest.TestCase):
    def test_threshold_equivalent_across_metrics(self):
        # Legacy default (L2 distance 1.35) corresponds to cosine similarity 0.325
        self.assertAlmostEqual(distance_to_similarity(1.35, "l2"), 0.325)
        self.assertAlmostEqual(distance_to_similarity(0.675, "cosine"), 0.325)
        self.assertAlmostEqual(distance_to_similarity(0.0, "cosine"), 1.0)


if __name__ == "__main__":
    unittest.main()
