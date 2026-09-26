"""Regression tests for authentication, rate limiting, SQL guard, and audit-chain hardening."""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import src.api.main as api_main
from src.api.main import app
from src.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from src.auth.login_throttle import login_throttle
from src.auth.user_store import user_store
from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db
from src.connectors.db_loader import DatabaseTableLoader, table_source_name
from src.core.audit import AuditLogger


def ensure_user(username: str, password: str, role: str):
    if user_store.get_user(username):
        user_store.delete_user(username)
    return user_store.create_user(username, password, role)


class TestTokenHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        self.user = ensure_user("token_user", "TokenPass123", "viewer")
        self.addCleanup(lambda: user_store.get_user("token_user") and user_store.delete_user("token_user"))

    def test_refresh_token_rejected_as_bearer(self):
        refresh, _ = create_refresh_token("token_user", "viewer")
        self.assertIsNone(decode_access_token(refresh))
        resp = self.client.get("/api/v1/documents", headers={"Authorization": f"Bearer {refresh}"})
        self.assertEqual(resp.status_code, 401)

    def test_access_token_rejected_by_refresh_endpoint(self):
        access, _ = create_access_token("token_user", "viewer")
        resp = self.client.post("/api/v1/auth/refresh", json={"refresh_token": access})
        self.assertEqual(resp.status_code, 401)

    def test_password_change_revokes_existing_tokens(self):
        login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "token_user", "password": "TokenPass123"},
        )
        tokens = login.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)

        user_store.update_user("token_user", password="NewTokenPass456")

        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)
        refresh = self.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(refresh.status_code, 401)

    def test_disabling_user_revokes_tokens(self):
        login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "token_user", "password": "TokenPass123"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        user_store.update_user("token_user", disabled=True)
        user_store.update_user("token_user", disabled=False)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_password_policy_enforced_on_update(self):
        with self.assertRaises(ValueError):
            user_store.update_user("token_user", password="weak")


class TestForcedPasswordChange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        ensure_user("pending_user", "PendingPass123", "viewer")
        user_store.update_user("pending_user", must_change_password=True)
        self.addCleanup(lambda: user_store.get_user("pending_user") and user_store.delete_user("pending_user"))
        patcher = patch("src.auth.dependencies.REQUIRE_DEFAULT_PASSWORD_CHANGE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _login(self, password):
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username": "pending_user", "password": password},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_pending_user_blocked_until_password_changed(self):
        tokens = self._login("PendingPass123")
        self.assertTrue(tokens["must_change_password"])
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        self.assertEqual(self.client.get("/api/v1/documents", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)

        weak = self.client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": "PendingPass123", "new_password": "short"},
        )
        self.assertEqual(weak.status_code, 400)

        wrong = self.client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": "Nope12345", "new_password": "BrandNewPass789"},
        )
        self.assertEqual(wrong.status_code, 400)

        changed = self.client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={
                "current_password": "PendingPass123",
                "new_password": "BrandNewPass789",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        new_tokens = changed.json()
        self.assertFalse(new_tokens["must_change_password"])

        new_headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=new_headers).status_code, 200)
        # Old token was revoked by the password change
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_login_with_insecure_default_password_sets_flag(self):
        ensure_user("default_pw_user", "Placeholder123", "viewer")
        self.addCleanup(lambda: user_store.get_user("default_pw_user") and user_store.delete_user("default_pw_user"))
        # Simulate a legacy account still on the built-in default password (bypasses the policy).
        # Patch the singleton itself. A string path through "src.auth.user_store" is fragile because
        # src.auth re-exports the `user_store` instance under the submodule's name.
        with patch.object(
            user_store,
            "authenticate_user",
            return_value=user_store.get_user("default_pw_user"),
        ):
            resp = self.client.post(
                "/api/v1/auth/login",
                json={"username": "default_pw_user", "password": "admin123"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["must_change_password"])
        self.assertTrue(user_store.get_user("default_pw_user").must_change_password)


class TestLoginThrottle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        ensure_user("throttle_user", "ThrottlePass123", "viewer")
        login_throttle.reset("throttle_user")
        self.addCleanup(login_throttle.reset, "throttle_user")
        self.addCleanup(lambda: user_store.get_user("throttle_user") and user_store.delete_user("throttle_user"))

    def test_account_locked_after_repeated_failures(self):
        for _ in range(login_throttle.max_failures):
            resp = self.client.post(
                "/api/v1/auth/login",
                json={"username": "throttle_user", "password": "wrong"},
            )
            self.assertEqual(resp.status_code, 401)

        locked = self.client.post(
            "/api/v1/auth/login",
            json={"username": "throttle_user", "password": "ThrottlePass123"},
        )
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Retry-After", locked.headers)

        # Other accounts are unaffected
        other = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(other.status_code, 200)


class TestRateLimitAndHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        api_main._rate_limit_store.clear()
        self.addCleanup(api_main._rate_limit_store.clear)

    def test_uvicorn_entrypoint_exports_app(self):
        """`uvicorn src.main:app` (README, Dockerfile) must keep resolving to the FastAPI app."""
        import src.main

        self.assertIs(src.main.app, app)

    def test_health_is_public(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_rate_limit_is_per_user_not_per_ip(self):
        token_a, _ = create_access_token("admin", "admin")
        ensure_user("rate_user_b", "RateUserB123", "viewer")
        self.addCleanup(lambda: user_store.get_user("rate_user_b") and user_store.delete_user("rate_user_b"))
        token_b, _ = create_access_token("rate_user_b", "viewer")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        with patch("src.api.main.RATE_LIMIT_PER_MINUTE", 2):
            for _ in range(2):
                self.assertEqual(
                    self.client.get("/api/v1/auth/me", headers=headers_a).status_code,
                    200,
                )
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers_a).status_code, 429)
            # Same client IP, different account: separate budget
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers_b).status_code, 200)
            # Health checks are exempt
            self.assertEqual(self.client.get("/health").status_code, 200)

    def test_feedback_validated_by_schema(self):
        token, _ = create_access_token("admin", "admin")
        resp = self.client.post(
            "/api/v1/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "q", "feedback": "meh"},
        )
        self.assertEqual(resp.status_code, 422)


class TestSqlGuardBypasses(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.temp_dir.name, "guard.db")
        create_sample_sqlite_db(db_path)
        self.url = f"sqlite:///{db_path}"
        self.connector = DatabaseConnector(database_url=self.url, allowed_tables=["urunler", "satislar"])

    def tearDown(self):
        self.connector.engine.dispose()
        self.temp_dir.cleanup()

    def assertAllowed(self, query):
        res = self.connector.execute_query(query)
        self.assertEqual(res["status"], "success", f"{query!r} -> {res.get('message')}")

    def assertBlocked(self, query):
        res = self.connector.execute_query(query)
        self.assertEqual(res["status"], "error", f"{query!r} should be blocked")

    def test_legitimate_queries_allowed(self):
        self.assertAllowed("SELECT u.urun_adi, s.adet FROM urunler u LEFT JOIN satislar s ON s.urun_id = u.urun_id")
        self.assertAllowed("WITH x AS (SELECT * FROM urunler) SELECT * FROM x")
        self.assertAllowed("SELECT * FROM urunler WHERE urun_adi = 'Delete update drop'")
        self.assertAllowed("SELECT REPLACE(urun_adi, 'a', 'b') FROM urunler")
        self.assertAllowed("SELECT * FROM urunler WHERE urun_id IN (SELECT urun_id FROM satislar)")

    def test_table_allowlist_bypasses_blocked(self):
        self.assertBlocked("SELECT * FROM urunler, destek_talepleri")
        self.assertBlocked('SELECT * FROM "destek_talepleri"')
        self.assertBlocked("SELECT * FROM main.destek_talepleri")
        self.assertBlocked("SELECT * FROM urunler WHERE urun_id IN (SELECT talep_id FROM destek_talepleri)")
        self.assertBlocked("SELECT * FROM urunler JOIN satislar ON 1=1, destek_talepleri")
        self.assertBlocked("SELECT * FROM sqlite_master")

    def test_dangerous_statements_and_functions_blocked(self):
        self.assertBlocked("SELECT 1; ATTACH DATABASE 'x.db' AS x")
        self.assertBlocked("SELECT * FROM urunler /* c */ ; DROP TABLE urunler")
        self.assertBlocked("SELECT load_extension('/tmp/evil')")
        self.assertBlocked("SELECT pg_read_file('/etc/passwd')")
        self.assertBlocked("SELECT * INTO backup FROM urunler")
        self.assertBlocked("WITH d AS (DELETE FROM urunler RETURNING *) SELECT * FROM d")
        self.assertBlocked("PRAGMA table_info(urunler)")

    def test_sqlite_session_is_read_only(self):
        with self.connector.engine.connect() as conn:
            with self.assertRaises(Exception):
                conn.exec_driver_sql("DELETE FROM urunler")

    def test_sync_deletes_same_source_it_indexes(self):
        """Re-syncing a table must remove the chunks previously indexed for it."""
        from src.services.database_service import DatabaseService
        import asyncio

        loader = DatabaseTableLoader(self.connector)
        _, _, metas = loader.load_table_as_chunks("urunler")
        self.assertEqual(metas[0]["source"], table_source_name("urunler"))

        engine = MagicMock()
        with (
            patch(
                "src.services.database_service.get_db_connector",
                return_value=self.connector,
            ),
            patch("src.services.database_service.get_db_loader", return_value=loader),
            patch("src.services.database_service.get_rag_engine", return_value=engine),
            patch("src.services.database_service.audit_logger.alog", new=AsyncMock()),
        ):
            asyncio.run(DatabaseService.sync_table("urunler", None, None, None, "admin", "admin"))
        engine.delete_document.assert_called_once_with(metas[0]["source"])


class TestAuditHashChain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "audit.db")
        self.audit = AuditLogger(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_intact_chain_verifies(self):
        for i in range(3):
            self.audit.log(username=f"u{i}", role="viewer", action="query", detail=f"q{i}")
        result = self.audit.verify_chain()
        self.assertTrue(result["valid"])
        self.assertEqual(result["checked_entries"], 3)
        self.assertIsNotNone(result["head_hash"])

    def test_tampered_entry_detected(self):
        ids = [self.audit.log(username="u", role="viewer", action="query", detail=f"q{i}") for i in range(3)]
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE audit_logs SET detail = 'forged' WHERE id = ?", (ids[1],))
        conn.commit()
        conn.close()
        result = self.audit.verify_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["first_invalid_id"], ids[1])

    def test_deleted_entry_detected(self):
        ids = [self.audit.log(username="u", role="viewer", action="query", detail=f"q{i}") for i in range(3)]
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM audit_logs WHERE id = ?", (ids[1],))
        conn.commit()
        conn.close()
        result = self.audit.verify_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["first_invalid_id"], ids[2])

    def test_legacy_database_is_migrated(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("""
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, username TEXT NOT NULL,
                user_role TEXT NOT NULL, action TEXT NOT NULL, detail TEXT, sources_used TEXT,
                answer_preview TEXT, ip_address TEXT, duration_ms INTEGER, status TEXT NOT NULL)
        """)
        conn.execute(
            "INSERT INTO audit_logs (timestamp, username, user_role, action, status) VALUES ('t', 'u', 'r', 'a', 's')"
        )
        conn.commit()
        conn.close()

        legacy_audit = AuditLogger(db_path=legacy_path)
        legacy_audit.log(username="u", role="viewer", action="query")
        result = legacy_audit.verify_chain()
        self.assertTrue(result["valid"])
        self.assertEqual(result["unverifiable_legacy_entries"], 1)
        self.assertEqual(result["checked_entries"], 1)

    def test_verify_endpoint_admin_only(self):
        client = TestClient(app, raise_server_exceptions=False)
        admin_token, _ = create_access_token("admin", "admin")
        resp = client.get(
            "/api/v1/admin/audit-verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("valid", resp.json())


if __name__ == "__main__":
    unittest.main()
