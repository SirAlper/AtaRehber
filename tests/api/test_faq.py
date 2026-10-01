"""Staff answers to unanswered questions: stored, searchable, shown to the users who asked, off the review list."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.audit import audit_logger
from src.services import faq as faq_module
from src.services.faq import FAQ_SOURCE, FaqStore, faq_chunks, reindex_faq
from src.services.review import question_of
from tests.api.test_access_and_requests import ensure_user


class TestFaqStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = FaqStore(os.path.join(self.tmp, "faq.json"))

    def test_answers_reach_the_users_who_asked_until_they_have_seen_them(self):
        asked = [
            {"username": "ayse", "question": "Yemekhane kaçta açılır?"},
            {"username": "ayse", "question": "yemekhane kaçta açılır"},
            {"username": "guest-1a2b", "question": "Yemekhane kaçta açılır?"},
        ]
        entry = self.store.add("Yemekhane kaçta açılır?", "Hafta içi 11.30'da.", "admin", ["Ogrenci"], asked)
        # Duplicates and guests (no account to show it to later) are left out; groups are normalized
        self.assertEqual(entry["asked"], [{"username": "ayse", "question": "Yemekhane kaçta açılır?"}])
        self.assertEqual(entry["groups"], ["ogrenci"])
        self.assertEqual([a["answer"] for a in self.store.unseen_for("ayse")], ["Hafta içi 11.30'da."])
        self.assertEqual(self.store.unseen_for("mehmet"), [])

        self.assertEqual(self.store.mark_seen("ayse", [entry["id"]]), 1)
        self.assertEqual(self.store.unseen_for("ayse"), [])
        # A corrected answer is shown again
        self.store.update(entry["id"], "Yemekhane kaçta açılır?", "Hafta içi 12.00'de.", [])
        self.assertEqual(len(self.store.unseen_for("ayse")), 1)
        self.assertTrue(self.store.delete(entry["id"]))
        self.assertFalse(self.store.delete(entry["id"]))

    def test_each_answer_is_one_chunk_with_the_access_groups_of_documents(self):
        entry = self.store.add("Soru bir?", "Cevap bir.", "admin", ["ogrenci"])
        documents, ids, metadatas = faq_chunks([entry])
        self.assertEqual(documents[0], f"[{FAQ_SOURCE} | Soru bir?]\nSoru bir?\nCevap bir.")
        self.assertEqual(ids, [f"faq_{entry['id']}"])
        self.assertEqual(metadatas[0]["source"], FAQ_SOURCE)
        self.assertEqual((metadatas[0]["acl_public"], metadatas[0]["acl_ogrenci"]), (False, True))

        engine = MagicMock()
        self.assertEqual(reindex_faq(engine, self.store), 1)
        engine.delete_document.assert_called_once_with(FAQ_SOURCE)
        self.assertEqual(engine.add_documents.call_args[0][1], ids)

    def test_audit_details_give_the_question(self):
        self.assertEqual(question_of("[doc_agent] Yemekhane kaçta?"), "Yemekhane kaçta?")
        self.assertEqual(question_of("[NEGATIVE] Q: Yemekhane kaçta?"), "Yemekhane kaçta?")
        self.assertEqual(question_of("[doc_agent] (question not stored, 16 chars)"), "")


class TestFaqLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        store = FaqStore(os.path.join(self.tmp, "faq.json"))
        self.engine = MagicMock()
        for target, value in (
            ("src.services.review.faq_store", store),
            ("src.api.routes.faq.faq_store", store),
            ("src.api.routes.faq.get_rag_engine", MagicMock(return_value=self.engine)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.question = f"Kampüs kreşi kaç yaşa kadar çocuk alır {id(self)}?"
        # The same question as another user types it
        self.variant = self.question.lower().replace(" ", "  ").rstrip("?")

    def ask(self, username, question):
        audit_logger.log(
            username=username, role="viewer", action="query_stream", detail=f"[doc_agent] {question}", status="warning"
        )

    def review(self, headers):
        return [
            i["question"] for i in self.client.get("/api/v1/admin/review?limit=200", headers=headers).json()["items"]
        ]

    def test_answering_reaches_everyone_who_asked_and_clears_the_review_list(self):
        editor = ensure_user("faq_editor", "editor")
        first = ensure_user("faq_user_1", "viewer")
        second = ensure_user("faq_user_2", "viewer")
        self.ask("faq_user_1", self.question)
        self.ask("faq_user_2", self.variant)
        self.assertEqual(self.review(editor).count(self.question), 1)

        response = self.client.post(
            "/api/v1/admin/faq", headers=editor, json={"question": self.question, "answer": "6 yaşına kadar."}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual({a["username"] for a in response.json()["entry"]["asked"]}, {"faq_user_1", "faq_user_2"})
        self.engine.add_documents.assert_called_once()
        self.assertNotIn(self.question, self.review(editor))
        self.assertNotIn(self.variant, self.review(editor))

        answers = self.client.get("/api/v1/faq/answers", headers=first).json()["answers"]
        self.assertEqual([a["answer"] for a in answers], ["6 yaşına kadar."])
        self.client.post("/api/v1/faq/answers/seen", headers=first, json={"ids": [answers[0]["id"]]})
        self.assertEqual(self.client.get("/api/v1/faq/answers", headers=first).json()["answers"], [])
        self.assertEqual(len(self.client.get("/api/v1/faq/answers", headers=second).json()["answers"]), 1)

    def test_only_staff_answer_and_guests_get_no_answers(self):
        viewer = ensure_user("faq_viewer", "viewer")
        response = self.client.post("/api/v1/admin/faq", headers=viewer, json={"question": "Soru?", "answer": "x"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/review", headers=viewer).status_code, 403)


class TestStartupIndexing(unittest.TestCase):
    def test_staff_answers_missing_from_the_index_are_indexed(self):
        from src.api import state

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = FaqStore(os.path.join(tmp, "faq.json"))
        store.add("Soru?", "Cevap.", "admin")
        engine = MagicMock()
        engine.get_stats.return_value = {"document_chunks": {}}
        with patch.object(faq_module, "faq_store", store), patch.object(state, "get_rag_engine", return_value=engine):
            state.index_faq_on_startup()
        engine.add_documents.assert_called_once()


if __name__ == "__main__":
    unittest.main()
