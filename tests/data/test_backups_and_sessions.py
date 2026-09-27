"""Conversation session cleanup, staged vector index restores, and the first-run sample database."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.agent.prompts import (
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
        from src.services import backups

        self.backups_module = backups
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
            ("DOCS_PATH", os.path.join(self.tmp, "no_data_dir")),
        ):
            patcher = patch.object(backups, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_restore_is_staged_then_applied_on_startup(self):
        backup_path = self.backups_module.backup_all()
        with open(os.path.join(self.vdb, "marker.txt"), "w") as f:
            f.write("changed after backup")

        self.assertTrue(self.backups_module.restore_vector_db(backup_path))
        # Live database untouched until restart
        with open(os.path.join(self.vdb, "marker.txt")) as f:
            self.assertEqual(f.read(), "changed after backup")

        self.assertTrue(self.backups_module.apply_pending_restore())
        with open(os.path.join(self.vdb, "marker.txt")) as f:
            self.assertEqual(f.read(), "live")
        pre_restore = [n for n in os.listdir(self.backups) if n.startswith("pre_restore_")]
        self.assertEqual(len(pre_restore), 1)
        with open(os.path.join(self.backups, pre_restore[0], "marker.txt")) as f:
            self.assertEqual(f.read(), "changed after backup")
        self.assertFalse(self.backups_module.apply_pending_restore())

    def test_restore_keeps_vector_db_directory_in_place(self):
        """In Docker the vector_db directory is a bind-mount point and must never be renamed or removed."""
        backup_path = self.backups_module.backup_all()
        original_inode = os.stat(self.vdb).st_ino
        self.backups_module.restore_vector_db(backup_path)
        with patch("src.services.backups.shutil.move", wraps=shutil.move) as move:
            self.assertTrue(self.backups_module.apply_pending_restore())
        moved_sources = [os.path.normpath(call.args[0]) for call in move.call_args_list]
        self.assertNotIn(os.path.normpath(self.vdb), moved_sources)
        self.assertEqual(os.stat(self.vdb).st_ino, original_inode)

    def test_backup_name_validation(self):
        self.assertTrue(self.backups_module.is_valid_backup_name("vector_db_backup_20260101_000000"))
        for bad in (
            "../vector_db",
            "vector_db_backup_../../etc",
            "other_dir",
            "",
            "a/vector_db_backup_1",
        ):
            self.assertFalse(self.backups_module.is_valid_backup_name(bad), bad)


class TestFirstRunSampleDatabase(unittest.TestCase):
    def test_connector_uses_sample_db_created_after_config_load(self):
        """On a fresh install the sample DB is created at startup, after DATABASE_URL was resolved as empty."""
        import src.api.state as state
        from src.connectors.sample_db import create_sample_sqlite_db

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
