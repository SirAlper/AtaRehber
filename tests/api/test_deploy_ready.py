"""Ready for any organization: web UI texts set by admins, and a clear answer when the language model is down."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.agent import llm
from src.api.main import app
from src.services.ui_settings import MAX_SUGGESTIONS, UiSettingsStore, default_language, normalize_settings
from tests.api.test_access_and_requests import ensure_user


class TestUiSettingsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = UiSettingsStore(os.path.join(self.tmp, "ui_settings.json"))

    def test_nothing_stored_means_the_built_in_texts(self):
        settings = self.store.get()
        self.assertEqual(settings["app_name"], "")
        self.assertEqual(settings["texts"]["tr"]["suggestions"], [])
        self.assertEqual(settings["texts"]["en"]["welcome"], "")

    def test_texts_are_cleaned_and_unknown_fields_dropped(self):
        settings = normalize_settings(
            {
                "app_name": "  AtaRehber\n",
                "theme": "red",
                "texts": {
                    "tr": {
                        "welcome": "Merhaba,\n  size   yardım ederim.",
                        "suggestions": ["Soru 1?", "", "Soru 1?"] + [f"Soru {i}?" for i in range(2, 10)],
                        "script": "<b>",
                    },
                    "de": {"welcome": "Hallo"},
                },
            }
        )
        self.assertEqual(settings["app_name"], "AtaRehber")
        self.assertEqual(set(settings["texts"]), {"tr", "en"})
        self.assertEqual(settings["texts"]["tr"]["welcome"], "Merhaba, size yardım ederim.")
        self.assertEqual(len(settings["texts"]["tr"]["suggestions"]), MAX_SUGGESTIONS)
        self.assertEqual(settings["texts"]["tr"]["suggestions"][:2], ["Soru 1?", "Soru 2?"])
        self.assertNotIn("script", settings["texts"]["tr"])

    def test_the_environment_gives_the_default_language_and_disclaimer(self):
        self.store.save({"texts": {"en": {"disclaimer": "Check the sources."}}}, "admin")
        with patch("src.services.ui_settings.UI_DISCLAIMER", "Resmî bilgi için birimlere başvurun."):
            public = self.store.public()
        self.assertEqual(public["texts"]["tr"]["disclaimer"], "Resmî bilgi için birimlere başvurun.")
        self.assertEqual(public["texts"]["en"]["disclaimer"], "Check the sources.")
        self.assertEqual((default_language("EN"), default_language("de"), default_language("")), ("en", "tr", "tr"))


class TestUiSettingsApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = patch(
            "src.api.routes.ui_settings.ui_settings_store", UiSettingsStore(os.path.join(self.tmp, "ui.json"))
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def test_admins_change_the_texts_everyone_reads_them_without_logging_in(self):
        admin = ensure_user("ui_admin", "admin")
        body = {"app_name": "AtaRehber", "texts": {"tr": {"suggestions": ["Burs başvurusu ne zaman?"]}}}
        response = self.client.put("/api/v1/admin/ui-settings", json=body, headers=admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_by"], "ui_admin")

        public = self.client.get("/api/v1/ui-settings").json()
        self.assertEqual(public["app_name"], "AtaRehber")
        self.assertEqual(public["texts"]["tr"]["suggestions"], ["Burs başvurusu ne zaman?"])
        self.assertIn(public["default_language"], ("tr", "en"))
        self.assertNotIn("updated_by", public)

    def test_only_admins_change_them_and_limits_hold(self):
        editor = ensure_user("ui_editor", "editor")
        self.assertEqual(self.client.put("/api/v1/admin/ui-settings", json={}, headers=editor).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/ui-settings", headers=editor).status_code, 403)
        admin = ensure_user("ui_admin", "admin")
        too_many = {"texts": {"tr": {"suggestions": ["?"] * (MAX_SUGGESTIONS + 1)}}}
        self.assertEqual(self.client.put("/api/v1/admin/ui-settings", json=too_many, headers=admin).status_code, 422)
        too_long = {"app_name": "x" * 41}
        self.assertEqual(self.client.put("/api/v1/admin/ui-settings", json=too_long, headers=admin).status_code, 422)


class TestLanguageModelOutage(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = ensure_user("outage_user", "viewer")
        self.orchestrator = MagicMock()
        for target, value in (
            ("src.core.config.LLM_STATUS_CHECK", True),
            ("src.api.routes.query.llm_problem", MagicMock(return_value="Ollama server is not reachable")),
            ("src.api.routes.query.get_multi_agent_orchestrator", MagicMock(return_value=self.orchestrator)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_questions_get_a_clear_unavailable_answer_without_running_the_agents(self):
        for path in ("/api/v1/query", "/api/v1/query-stream"):
            response = self.client.post(path, json={"question": "İzin süresi nedir?"}, headers=self.headers)
            self.assertEqual(response.status_code, 503, path)
            self.assertEqual(response.headers["X-Error-Code"], "llm_unavailable")
            self.assertIn("language model is not available", response.json()["detail"])
        self.orchestrator.query.assert_not_called()
        self.orchestrator.stream_events.assert_not_called()

    def test_with_the_model_back_questions_run(self):
        self.orchestrator.query.return_value = {"answer": "15 gün.", "sources": []}
        with patch("src.api.routes.query.llm_problem", MagicMock(return_value=None)):
            response = self.client.post("/api/v1/query", json={"question": "İzin süresi?"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "15 gün.")


class TestLlmStatusCache(unittest.TestCase):
    def setUp(self):
        llm._status.update(checked_at=None, problem=None)
        self.addCleanup(llm._status.update, checked_at=None, problem=None)

    def test_the_check_is_reused_for_a_while_then_repeated(self):
        with patch("src.agent.llm.check_ollama", MagicMock(side_effect=["down", None])) as check:
            self.assertEqual(llm.llm_problem(max_age=60), "down")
            self.assertEqual(llm.llm_problem(max_age=60), "down")
            self.assertEqual(check.call_count, 1)
            self.assertIsNone(llm.llm_problem(max_age=0))
            self.assertEqual(check.call_count, 2)


class TestEnvironmentExample(unittest.TestCase):
    def test_new_settings_are_documented(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, ".env.example"), encoding="utf-8") as f:
            example = f.read()
        for name in ("LLM_STATUS_CHECK", "LLM_STATUS_CACHE_SECONDS", "UI_LANGUAGE", "UI_DISCLAIMER"):
            self.assertIn(name, example)


if __name__ == "__main__":
    unittest.main()
