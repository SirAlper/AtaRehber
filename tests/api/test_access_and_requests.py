"""Document access groups, service requests (store, API, e-mail), per-task models, and the demo database switch."""

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import chromadb
import numpy as np
from fastapi.testclient import TestClient

import src.api.state as state
from src.agent import llm
from src.api import maintenance
from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.auth.user_store import user_store
from src.core import config
from src.services import notifier
from src.services.document_service import DocumentService
from src.auth.document_access import (
    DocumentAccessStore,
    access_metadata,
    ONLY_GROUPS,
    allowed_groups_for,
    document_access_store,
    normalize_groups,
    search_filter,
)
from src.services.service_requests import ServiceRequestStore, get_request_store, normalize_category
from src.rag.rag_engine import RAGEngine

PASSWORD = "Passw0rdX"


def ensure_user(username, role, groups=()):
    """Create a test user once per session and return auth headers."""
    try:
        user_store.create_user(username, PASSWORD, role, groups=list(groups))
    except ValueError:
        user_store.update_user(username, groups=list(groups))
    token, _ = create_access_token(username, role)
    return {"Authorization": f"Bearer {token}"}


class TestAccessRules(unittest.TestCase):
    def test_group_names_are_normalized_and_validated(self):
        self.assertEqual(normalize_groups("Akademik, idari ,akademik"), ["akademik", "idari"])
        self.assertEqual(normalize_groups(None), [])
        with self.assertRaises(ValueError):
            normalize_groups(["bad group!"])

    def test_metadata_revokes_groups_that_lost_access(self):
        self.assertEqual(access_metadata([]), {"acl_public": True})
        self.assertEqual(
            access_metadata(["akademik"], previous_groups=["idari"]),
            {"acl_public": False, "acl_akademik": True, "acl_idari": False},
        )

    def test_managers_are_not_filtered(self):
        self.assertIsNone(allowed_groups_for("admin", ["x"]))
        self.assertIsNone(allowed_groups_for("editor", []))
        # Documents shared with visitors are public information: every account also sees them
        self.assertEqual(allowed_groups_for("viewer", ["akademik"]), ["akademik", "ziyaretci"])
        self.assertEqual(search_filter([]), {"acl_public": {"$ne": False}})
        self.assertEqual(len(search_filter(["a", "b"])["$or"]), 3)

    def test_guests_only_search_the_visitor_group(self):
        scope = allowed_groups_for("guest", ["akademik"])
        self.assertEqual(scope, [ONLY_GROUPS, "ziyaretci"])
        self.assertEqual(search_filter(scope), {"acl_ziyaretci": True})
        # No group left: nothing matches, public documents included
        self.assertEqual(search_filter([ONLY_GROUPS]), {"acl_": True})

    def test_store_decides_visibility(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = DocumentAccessStore(os.path.join(tmp, "access.json"))
        store.set("gizli.pdf", ["akademik"])
        self.assertTrue(store.can_access("acik.pdf", "viewer", []))
        self.assertFalse(store.can_access("gizli.pdf", "viewer", ["idari"]))
        self.assertTrue(store.can_access("gizli.pdf", "viewer", ["akademik"]))
        self.assertTrue(store.can_access("gizli.pdf", "editor", []))
        store.set("aof.pdf", ["ziyaretci"])
        self.assertFalse(store.can_access("acik.pdf", "guest", []))
        self.assertFalse(store.can_access("gizli.pdf", "guest", []))
        self.assertTrue(store.can_access("aof.pdf", "guest", []))
        self.assertTrue(store.can_access("aof.pdf", "viewer", ["idari"]))
        store.set("aof.pdf", [])
        self.assertEqual(store.set("gizli.pdf", []), ["akademik"])  # returns the previous groups
        self.assertEqual(store.all(), {})


class TestVectorStoreFiltering(unittest.TestCase):
    """Real ChromaDB filtering with stand-in embedding and reranker models."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        engine = object.__new__(RAGEngine)
        engine.client = chromadb.PersistentClient(
            path=self.tmp, settings=chromadb.config.Settings(anonymized_telemetry=False)
        )
        engine.collection = engine.client.get_or_create_collection("acl_test", metadata={"hnsw:space": "cosine"})
        engine.distance_space = "cosine"
        engine.embedding_model = MagicMock()
        engine.embedding_model.encode.side_effect = lambda texts, **kw: (
            np.ones((len(texts), 4)) if isinstance(texts, list) else np.ones(4)
        )
        engine.reranker = MagicMock()
        engine.reranker.predict.side_effect = lambda pairs: [0.9] * len(pairs)
        engine.write_lock = threading.RLock()
        engine._stats_cache = None
        self.engine = engine
        docs = {
            "acik.txt": {},
            "akademik.txt": access_metadata(["akademik"]),
            "idari.txt": access_metadata(["idari"]),
            "aof.txt": access_metadata(["ziyaretci"]),
        }
        for name, acl in docs.items():
            engine.add_documents([f"{name} içerik"], [name], [{"source": name, "chunk_index": 0, **acl}])

    def visible(self, groups):
        result = self.engine.search("soru", min_similarity=-2, min_reranker_score=0, top_n=10, allowed_groups=groups)
        return sorted(s["source"] for s in result["sources"])

    def test_users_see_public_documents_and_their_groups(self):
        self.assertEqual(self.visible(None), ["acik.txt", "akademik.txt", "aof.txt", "idari.txt"])
        self.assertEqual(self.visible([]), ["acik.txt"])
        self.assertEqual(self.visible(["akademik"]), ["acik.txt", "akademik.txt"])
        self.assertEqual(self.visible(allowed_groups_for("viewer", [])), ["acik.txt", "aof.txt"])

    def test_guests_see_only_documents_shared_with_visitors(self):
        self.assertEqual(self.visible(allowed_groups_for("guest", [])), ["aof.txt"])

    def test_changing_groups_revokes_the_old_group(self):
        self.engine.update_document_metadata("akademik.txt", access_metadata(["idari"], previous_groups=["akademik"]))
        self.assertEqual(self.visible(["akademik"]), ["acik.txt"])
        self.assertEqual(self.visible(["idari"]), ["acik.txt", "akademik.txt", "idari.txt"])
        self.engine.update_document_metadata("idari.txt", access_metadata([], previous_groups=["idari"]))
        self.assertEqual(self.visible([]), ["acik.txt", "idari.txt"])


class TestDocumentAccessApi(unittest.TestCase):
    filename = "acl_test_regulation.txt"

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.editor = ensure_user("acl_editor", "editor")
        cls.viewer_academic = ensure_user("acl_viewer_a", "viewer", ["akademik"])
        cls.viewer_other = ensure_user("acl_viewer_b", "viewer", ["idari"])

    def setUp(self):
        self.engine = MagicMock()
        self.engine.get_stats.return_value = {"document_chunks": {self.filename: 1}, "total_chunks": 1}
        patcher = patch("src.services.document_service.get_rag_engine", return_value=self.engine)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(document_access_store.remove, self.filename)
        path = os.path.join(config.DOCS_PATH, self.filename)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

    def upload(self, groups):
        return self.client.post(
            "/api/v1/upload-file",
            headers=self.editor,
            files={"file": (self.filename, "Madde 1 - Akademik personel kuralı.".encode(), "text/plain")},
            data={"groups": groups},
        )

    def listed(self, headers):
        return [d["filename"] for d in self.client.get("/api/v1/documents", headers=headers).json()["documents"]]

    def test_restricted_upload_is_only_visible_to_its_groups(self):
        response = self.upload("Akademik")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["groups"], ["akademik"])
        metadatas = self.engine.add_documents.call_args.args[2]
        self.assertTrue(all(m["acl_akademik"] and m["acl_public"] is False for m in metadatas))

        self.assertIn(self.filename, self.listed(self.viewer_academic))
        self.assertNotIn(self.filename, self.listed(self.viewer_other))
        self.assertIn(self.filename, self.listed(self.editor))
        stats = self.client.get("/api/v1/stats", headers=self.viewer_other).json()
        self.assertEqual(stats["total_documents"], 0)

    def test_a_document_is_listed_as_indexing_until_its_chunks_are_stored(self):
        def listed_entry():
            documents = DocumentService.list_documents(role="editor")["documents"]
            return next(d for d in documents if d["filename"] == self.filename)

        during = []
        self.engine.get_stats.return_value = {"document_chunks": {}, "total_chunks": 0}
        self.engine.add_documents.side_effect = lambda *args: during.append(listed_entry())
        self.assertEqual(self.upload("").status_code, 200)
        self.assertEqual((during[0]["indexing"], during[0]["chunk_count"]), (True, 0))
        self.assertFalse(listed_entry()["indexing"])

        # A failed indexing does not leave the file marked as indexing forever
        self.engine.add_documents.side_effect = RuntimeError("embedding failed")
        self.assertEqual(self.upload("").status_code, 500)
        self.assertFalse(listed_entry()["indexing"])

    def test_access_can_be_changed_and_is_cleared_on_delete(self):
        self.upload("akademik")
        response = self.client.put(
            f"/api/v1/documents/{self.filename}/access", headers=self.editor, json={"groups": ["idari"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.engine.update_document_metadata.assert_called_with(
            self.filename, {"acl_public": False, "acl_idari": True, "acl_akademik": False}
        )
        self.assertIn(self.filename, self.listed(self.viewer_other))

        self.engine.delete_document.return_value = 1
        self.client.delete(f"/api/v1/documents/{self.filename}", headers=self.editor)
        self.assertEqual(document_access_store.get(self.filename), [])

    def test_invalid_access_changes_are_rejected(self):
        self.assertEqual(self.upload("bad group!").status_code, 400)
        response = self.client.put(
            "/api/v1/documents/not_indexed.txt/access", headers=self.editor, json={"groups": ["idari"]}
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.put(
            f"/api/v1/documents/{self.filename}/access", headers=self.viewer_academic, json={"groups": []}
        )
        self.assertEqual(response.status_code, 403)


class TestUserGroupsAndQueryContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        token, _ = create_access_token("admin", "admin")
        cls.admin = {"Authorization": f"Bearer {token}"}

    def test_admin_sets_groups(self):
        ensure_user("group_target", "viewer")
        response = self.client.patch(
            "/api/v1/auth/users/group_target", headers=self.admin, json={"groups": ["Akademik", "idari"]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["groups"], ["akademik", "idari"])
        bad = self.client.patch("/api/v1/auth/users/group_target", headers=self.admin, json={"groups": ["a b"]})
        self.assertEqual(bad.status_code, 400)

    def test_query_passes_the_user_to_the_agents(self):
        headers = ensure_user("context_viewer", "viewer", ["akademik"])
        orchestrator = MagicMock()
        orchestrator.query.return_value = {"answer": "a", "sources": [], "active_agent": "doc_agent", "agents": []}
        with patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=orchestrator):
            response = self.client.post("/api/v1/query", headers=headers, json={"question": "Soru?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            orchestrator.query.call_args.kwargs["user"],
            {"username": "context_viewer", "role": "viewer", "groups": ["akademik"], "profile": {}},
        )

    def test_admins_record_a_profile_that_reaches_the_agents(self):
        admin = ensure_user("profile_admin", "admin")
        headers = ensure_user("profile_student", "viewer")
        profile = {"unit": " Mühendislik  Fakültesi ", "program": "Bilgisayar Mühendisliği", "level": ""}
        response = self.client.patch("/api/v1/auth/users/profile_student", headers=admin, json={"profile": profile})
        self.assertEqual(response.status_code, 200, response.text)
        cleaned = {"unit": "Mühendislik Fakültesi", "program": "Bilgisayar Mühendisliği"}
        self.assertEqual(response.json()["profile"], cleaned)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).json()["profile"], cleaned)

        orchestrator = MagicMock()
        orchestrator.query.return_value = {"answer": "a", "sources": [], "active_agent": "doc_agent", "agents": []}
        with patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=orchestrator):
            self.client.post("/api/v1/query", headers=headers, json={"question": "Bölümümde devam zorunlu mu?"})
        self.assertEqual(orchestrator.query.call_args.kwargs["user"]["profile"], cleaned)

        bad = self.client.patch("/api/v1/auth/users/profile_student", headers=admin, json={"profile": {"age": "20"}})
        self.assertEqual(bad.status_code, 400)


class TestRequestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = ServiceRequestStore(os.path.join(self.tmp, "requests.db"))

    def test_create_list_update(self):
        first = self.store.create("ayse", "IT Support", "  Projektör   bozuk ", "B204")
        self.store.create("mehmet", "unknown-category", "Klima")
        self.assertEqual(
            (first["category"], first["title"], first["status"]), ("it_support", "Projektör bozuk", "open")
        )
        self.assertEqual([r["title"] for r in self.store.list(username="ayse")], ["Projektör bozuk"])
        self.assertEqual(self.store.list(username="mehmet")[0]["category"], "other")
        updated = self.store.update_status(first["id"], "resolved", "bidb", "Lamba değişti")
        self.assertEqual((updated["status"], updated["resolution_note"]), ("resolved", "Lamba değişti"))
        self.assertIsNone(self.store.update_status(999, "resolved", "x"))
        with self.assertRaises(ValueError):
            self.store.update_status(first["id"], "done", "x")
        with self.assertRaises(ValueError):
            self.store.create("ayse", "other", "ab")

    def test_retention_deletes_only_old_closed_requests(self):
        old_closed = self.store.create("u", "other", "Eski kapalı")
        self.store.update_status(old_closed["id"], "resolved", "x")
        old_open = self.store.create("u", "other", "Eski açık")
        self.store.create("u", "other", "Yeni")
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE service_requests SET updated_at = ? WHERE id IN (?, ?)", (old, old_closed["id"], old_open["id"])
            )
        self.assertEqual(self.store.purge_closed_older_than_days(30), 1)
        self.assertEqual(len(self.store.list()), 2)

    def test_unknown_category_falls_back_to_other(self):
        self.assertEqual(normalize_category("Facilities"), "facilities")
        self.assertEqual(normalize_category("kütüphane"), "other")


class TestRequestsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.owner = ensure_user("req_owner", "viewer")
        cls.other = ensure_user("req_other", "viewer")
        cls.staff = ensure_user("req_staff", "editor")

    def create(self, title="Yazıcı çalışmıyor"):
        response = self.client.post(
            "/api/v1/requests",
            headers=self.owner,
            json={"category": "it_support", "title": title, "description": "3. kat"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["request"]["id"]

    def patch_status(self, headers, request_id, status, note=""):
        return self.client.patch(
            f"/api/v1/requests/{request_id}", headers=headers, json={"status": status, "resolution_note": note}
        )

    def test_users_only_see_and_cancel_their_own_requests(self):
        request_id = self.create()
        mine = self.client.get("/api/v1/requests", headers=self.owner).json()["requests"]
        self.assertIn(request_id, [r["id"] for r in mine])
        others = self.client.get("/api/v1/requests?all_users=true", headers=self.other).json()["requests"]
        self.assertNotIn(request_id, [r["id"] for r in others])  # viewers cannot list everyone

        self.assertEqual(self.patch_status(self.other, request_id, "cancelled").status_code, 404)
        self.assertEqual(self.patch_status(self.owner, request_id, "resolved").status_code, 403)
        self.assertEqual(self.patch_status(self.owner, request_id, "cancelled").status_code, 200)
        self.assertEqual(self.patch_status(self.owner, request_id, "cancelled").status_code, 403)  # no longer open

    def test_staff_work_off_all_requests(self):
        request_id = self.create("Klima arızası")
        listed = self.client.get("/api/v1/requests?all_users=true", headers=self.staff).json()["requests"]
        self.assertIn(request_id, [r["id"] for r in listed])
        response = self.patch_status(self.staff, request_id, "resolved", "Servis çağrıldı")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["request"]["updated_by"], "req_staff")
        self.assertEqual(get_request_store().get(request_id)["resolution_note"], "Servis çağrıldı")

    def test_invalid_status_is_rejected(self):
        self.assertEqual(self.patch_status(self.staff, self.create("Test"), "done").status_code, 422)


class TestNotifications(unittest.TestCase):
    request = {
        "id": 7,
        "category": "it_support",
        "username": "ayse",
        "title": "Projektör bozuk",
        "description": "B204",
        "created_at": "2026-09-27T10:00:00+00:00",
    }

    def test_recipient_by_category_with_default(self):
        with patch.object(
            notifier, "REQUEST_NOTIFY_EMAILS", {"it_support": "bidb@uni.edu", "default": "genel@uni.edu"}
        ):
            self.assertEqual(notifier.request_recipient("it_support"), "bidb@uni.edu")
            self.assertEqual(notifier.request_recipient("facilities"), "genel@uni.edu")
        with patch.object(notifier, "REQUEST_NOTIFY_EMAILS", {}):
            self.assertIsNone(notifier.request_recipient("it_support"))
            self.assertFalse(notifier.notify_new_request(self.request))

    def send(self, include_details):
        smtp = MagicMock()
        with (
            patch.object(notifier, "REQUEST_NOTIFY_EMAILS", {"default": "genel@uni.edu"}),
            patch.object(notifier, "SMTP_HOST", "smtp.uni.edu"),
            patch.object(notifier, "REQUEST_NOTIFY_INCLUDE_DETAILS", include_details),
            patch("smtplib.SMTP", return_value=smtp),
        ):
            self.assertTrue(notifier.notify_new_request(self.request))
        sent = smtp.__enter__.return_value.send_message.call_args.args[0]
        return sent["To"], sent["Subject"], sent.get_content()

    def test_email_goes_only_to_the_configured_address(self):
        to, subject, body = self.send(include_details=True)
        self.assertEqual(to, "genel@uni.edu")
        self.assertIn("Projektör bozuk", subject)
        self.assertIn("ayse", body)

    def test_details_can_be_left_out_of_emails(self):
        _, subject, body = self.send(include_details=False)
        self.assertNotIn("Projektör", subject + body)
        self.assertNotIn("ayse", body)
        self.assertIn("#7", subject)

    def test_email_is_off_without_smtp_host(self):
        with patch.object(notifier, "SMTP_HOST", ""):
            self.assertFalse(notifier.send_email("x@uni.edu", "s", "b"))


class TestModelsAndMaintenance(unittest.TestCase):
    def test_every_configured_model_must_be_pulled(self):
        tags = MagicMock()
        tags.__enter__.return_value.read.return_value = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
        with (
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch.object(llm, "OLLAMA_GRADER_MODEL", "qwen3:14b"),
            patch.object(llm, "OLLAMA_ROUTER_MODEL", ""),
            patch("urllib.request.urlopen", return_value=tags),
        ):
            self.assertEqual(llm.configured_models(), ["qwen2.5:7b", "qwen3:14b"])
            self.assertEqual(llm.router_model_name(), "qwen2.5:7b")
            self.assertIn("ollama pull qwen3:14b", llm.check_ollama())

    def test_maintenance_applies_request_retention(self):
        store = MagicMock()
        store.purge_closed_older_than_days.return_value = 2
        with (
            patch.object(config, "REQUEST_RETENTION_DAYS", 30),
            patch.object(config, "AUDIT_RETENTION_DAYS", 0),
            patch.object(config, "SESSION_RETENTION_DAYS", 0),
            patch.object(config, "BACKUP_INTERVAL_HOURS", 0),
            patch("src.services.service_requests.get_request_store", return_value=store),
        ):
            self.assertEqual(maintenance.run_maintenance_once(), {"requests_deleted": 2})
        store.purge_closed_older_than_days.assert_called_once_with(30)

    def test_demo_database_can_be_disabled(self):
        original = state.db_connector
        self.addCleanup(setattr, state, "db_connector", original)
        state.db_connector = None
        with patch.object(state, "SAMPLE_DB_ENABLED", False), patch.object(state, "DATABASE_URL", ""):
            self.assertFalse(state.get_db_connector().is_connected)


if __name__ == "__main__":
    unittest.main()
