"""Retention policy (audit log, sessions), question-text logging option, full and scheduled backups."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import src.api.state as state
from src.api import maintenance
from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.core import config
from src.core.audit import AuditLogger


class TestAuditRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.audit = AuditLogger(db_path=os.path.join(self.tmp, "audit.db"))

    def _backdate(self, entry_id: int, days: int):
        """Rewrite an entry's timestamp *and* hash, as if it had been written `days` days ago."""
        from src.core.audit import GENESIS_HASH, compute_entry_hash

        with sqlite3.connect(self.audit.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY id").fetchall()
            prev = GENESIS_HASH
            for row in rows:
                ts = row["timestamp"]
                if row["id"] <= entry_id:
                    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                entry_hash = compute_entry_hash(
                    prev, ts, row["username"], row["user_role"], row["action"], row["detail"],
                    row["sources_used"], row["answer_preview"], row["ip_address"], row["duration_ms"], row["status"],
                )  # fmt: skip
                conn.execute(
                    "UPDATE audit_logs SET timestamp = ?, prev_hash = ?, entry_hash = ? WHERE id = ?",
                    (ts, prev, entry_hash, row["id"]),
                )
                prev = entry_hash

    def test_purge_keeps_the_remaining_chain_verifiable(self):
        ids = [self.audit.log("u", "viewer", "query", detail=f"q{i}") for i in range(5)]
        self._backdate(ids[2], days=400)  # entries 1-3 are old
        self.assertTrue(self.audit.verify_chain()["valid"])

        deleted = self.audit.purge_older_than_days(365)

        self.assertEqual(deleted, 3)
        result = self.audit.verify_chain()
        self.assertTrue(result["valid"], result)
        self.assertIsNotNone(result["purged_before"])
        remaining = self.audit.query_logs(limit=100)
        # Two recent entries plus the entry that records the purge itself
        self.assertEqual(sorted(e["action"] for e in remaining), ["query", "query", "retention_purge"])

    def test_tampering_after_purge_is_still_detected(self):
        ids = [self.audit.log("u", "viewer", "query", detail=f"q{i}") for i in range(4)]
        self._backdate(ids[1], days=400)
        self.audit.purge_older_than_days(365)
        with sqlite3.connect(self.audit.db_path) as conn:
            conn.execute("UPDATE audit_logs SET detail = 'forged' WHERE id = ?", (ids[3],))
        result = self.audit.verify_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["first_invalid_id"], ids[3])

    def test_nothing_to_purge(self):
        self.audit.log("u", "viewer", "query", detail="recent")
        self.assertEqual(self.audit.purge_older_than_days(30), 0)
        self.assertIsNone(self.audit.verify_chain()["purged_before"])


class TestQuestionTextLogging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        token, _ = create_access_token("admin", "admin")
        cls.headers = {"Authorization": f"Bearer {token}"}

    def _query_and_capture_audit(self):
        orchestrator = MagicMock()
        orchestrator.query.return_value = {
            "answer": "Yıllık izin 20 gündür.",
            "sources": [],
            "active_agent": "doc_agent",
        }
        with (
            patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=orchestrator),
            patch("src.api.routes.query.audit_logger") as audit,
        ):
            audit.alog = MagicMock(side_effect=lambda **kwargs: _async_none())
            resp = self.client.post(
                "/api/v1/query", headers=self.headers, json={"question": "Ahmet Yılmaz'ın izni kaç gün?"}
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        return audit.alog.call_args.kwargs

    def test_question_text_is_logged_by_default(self):
        entry = self._query_and_capture_audit()
        self.assertIn("Ahmet Yılmaz", entry["detail"])
        self.assertEqual(entry["answer_preview"], "Yıllık izin 20 gündür.")

    def test_question_text_can_be_disabled(self):
        with patch.object(config, "AUDIT_STORE_QUESTIONS", False):
            entry = self._query_and_capture_audit()
        self.assertNotIn("Ahmet", entry["detail"])
        self.assertIn("question not stored", entry["detail"])
        self.assertIn("[doc_agent]", entry["detail"])
        self.assertIsNone(entry["answer_preview"])


async def _async_none():
    return None


class TestFullBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        self.vdb = os.path.join(self.tmp, "vector_db")
        self.backups = os.path.join(self.tmp, "backups")
        os.makedirs(os.path.join(self.data, "archive"))
        os.makedirs(self.vdb)
        with open(os.path.join(self.vdb, "chroma.sqlite3"), "w") as f:
            f.write("index")
        with open(os.path.join(self.data, "yonetmelik.pdf"), "wb") as f:
            f.write(b"%PDF-1.4")
        with open(os.path.join(self.data, "archive", "old.txt"), "w") as f:
            f.write("old")
        with open(os.path.join(self.data, "users.json"), "w") as f:
            json.dump({"admin": {}}, f)
        with open(os.path.join(self.data, ".jwt_secret"), "w") as f:
            f.write("secret")
        # A SQLite database in WAL mode with an open writer, like the live audit log
        self.live = sqlite3.connect(os.path.join(self.data, "audit.db"))
        self.live.execute("PRAGMA journal_mode=WAL")
        self.live.execute("CREATE TABLE t (x)")
        self.live.execute("INSERT INTO t VALUES (42)")
        self.live.commit()
        self.addCleanup(self.live.close)
        for name, value in (
            ("DOCS_PATH", self.data),
            ("VECTOR_DB_PATH", self.vdb),
            ("BACKUP_DIR", self.backups),
            ("PENDING_RESTORE_PATH", os.path.join(self.backups, ".restore_pending")),
            ("rag_engine", None),
        ):
            patcher = patch.object(state, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_full_backup_contains_index_and_data_but_not_the_secret(self):
        path = state.backup_all()
        self.assertTrue(os.path.basename(path).startswith(state.FULL_BACKUP_PREFIX))
        self.assertTrue(os.path.isfile(os.path.join(path, "vector_db", "chroma.sqlite3")))
        for rel in ("yonetmelik.pdf", "users.json", os.path.join("archive", "old.txt")):
            self.assertTrue(os.path.isfile(os.path.join(path, "data", rel)), rel)
        self.assertFalse(os.path.exists(os.path.join(path, "data", ".jwt_secret")))
        self.assertFalse(any(n.endswith(("-wal", "-shm")) for n in os.listdir(os.path.join(path, "data"))))
        # The WAL database copy is complete and readable on its own
        with sqlite3.connect(os.path.join(path, "data", "audit.db")) as copy:
            self.assertEqual(copy.execute("SELECT x FROM t").fetchone()[0], 42)

    def test_full_backup_is_listed_and_its_index_can_be_restored(self):
        path = state.backup_all()
        listed = state.list_backups()
        self.assertEqual((listed[0]["name"], listed[0]["type"]), (os.path.basename(path), "full"))
        self.assertTrue(state.is_valid_backup_name(os.path.basename(path)))

        self.assertTrue(state.restore_vector_db(path))
        staged = os.listdir(state.PENDING_RESTORE_PATH)
        self.assertEqual(staged, ["chroma.sqlite3"])  # the index only, not the data directory

    def test_prune_keeps_the_newest_full_backups(self):
        os.makedirs(self.backups)
        for stamp in ("20260101_000000", "20260102_000000", "20260103_000000"):
            os.makedirs(os.path.join(self.backups, f"{state.FULL_BACKUP_PREFIX}{stamp}"))
        os.makedirs(os.path.join(self.backups, f"{state.BACKUP_PREFIX}20260101_000000"))

        self.assertEqual(state.prune_full_backups(keep=2), 1)
        names = sorted(os.listdir(self.backups))
        self.assertNotIn(f"{state.FULL_BACKUP_PREFIX}20260101_000000", names)
        self.assertIn(f"{state.BACKUP_PREFIX}20260101_000000", names)  # vector-only backups untouched
        self.assertEqual(state.latest_full_backup_time(), datetime(2026, 1, 3, tzinfo=timezone.utc))

    def test_scheduled_maintenance(self):
        audit = MagicMock()
        with (
            patch.object(config, "BACKUP_INTERVAL_HOURS", 24),
            patch.object(config, "BACKUP_KEEP", 7),
            patch.object(config, "AUDIT_RETENTION_DAYS", 180),
            patch.object(config, "SESSION_RETENTION_DAYS", 30),
            patch.object(maintenance, "audit_logger", audit),
            patch.object(state, "cleanup_expired_sessions", return_value=2) as sessions,
        ):
            audit.purge_older_than_days.return_value = 5
            first = maintenance.run_maintenance_once()
            second = maintenance.run_maintenance_once()  # the backup is not due again yet

        self.assertEqual(first["audit_entries_deleted"], 5)
        self.assertEqual(first["sessions_deleted"], 2)
        self.assertIn("backup_path", first)
        self.assertNotIn("backup_path", second)
        audit.purge_older_than_days.assert_called_with(180)
        sessions.assert_called_with(max_age_days=30)

    def test_maintenance_does_nothing_by_default(self):
        self.assertEqual(maintenance.run_maintenance_once(), {})
        self.assertFalse(os.path.exists(self.backups))


if __name__ == "__main__":
    unittest.main()
