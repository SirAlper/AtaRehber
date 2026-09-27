import asyncio
import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_ollama import ChatOllama

from src.agent import llm
from src.api.main import app
from src.api.state import QueryConcurrencyManager
from src.auth.jwt_handler import create_access_token


def ollama_tags(*names):
    """Fake response of GET /api/tags."""
    body = json.dumps({"models": [{"name": n, "model": n} for n in names]}).encode()
    response = io.BytesIO(body)
    response.__enter__ = lambda self=response: self
    response.__exit__ = lambda *args: False
    return response


class TestOllamaChatModel(unittest.TestCase):
    def test_create_chat_model_uses_configured_ollama_settings(self):
        with (
            patch.object(llm, "OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch.object(llm, "OLLAMA_NUM_CTX", 8192),
        ):
            model = llm.create_chat_model()
        self.assertIsInstance(model, ChatOllama)
        self.assertEqual(model.model, "qwen2.5:7b")
        self.assertEqual(model.base_url, "http://127.0.0.1:11434")
        self.assertEqual(model.num_ctx, 8192)
        self.assertEqual(model.temperature, 0.0)

    def test_removed_huggingface_settings_are_reported(self):
        with (
            patch.dict("os.environ", {"LLM_BACKEND": "huggingface", "LLM_MODEL_ID": "Qwen/Qwen2.5-1.5B-Instruct"}),
            self.assertLogs(llm.logger, level="WARNING") as logs,
        ):
            llm.create_chat_model()
        self.assertIn("LLM_BACKEND, LLM_MODEL_ID", logs.output[0])

    def test_llm_backend_ollama_is_not_reported(self):
        with patch.dict("os.environ", {"LLM_BACKEND": "ollama"}), patch.object(llm.logger, "warning") as warning:
            llm.create_chat_model()
        warning.assert_not_called()


class TestCheckOllama(unittest.TestCase):
    def test_ok_when_model_is_pulled(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch("urllib.request.urlopen", return_value=ollama_tags("qwen2.5:7b", "bge-m3:latest")),
        ):
            self.assertIsNone(llm.check_ollama())

    def test_untagged_model_name_matches_latest(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "llama3.1"),
            patch("urllib.request.urlopen", return_value=ollama_tags("llama3.1:latest")),
        ):
            self.assertIsNone(llm.check_ollama())

    def test_missing_model_tells_how_to_pull_it(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch("urllib.request.urlopen", return_value=ollama_tags("qwen2.5-coder:7b")),
        ):
            problem = llm.check_ollama()
        self.assertIn("ollama pull qwen2.5:7b", problem)

    def test_unreachable_server(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            problem = llm.check_ollama()
        self.assertIn("not reachable", problem)


class TestStatsAndConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        token, _ = create_access_token("admin", "admin")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    def _stats(self, llm_problem):
        mock_engine = MagicMock()
        mock_engine.get_stats.return_value = {"total_chunks": 0, "total_documents": 0, "document_chunks": {}}
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = {"status": "not_configured"}
        with (
            patch("src.services.document_service.get_rag_engine", return_value=mock_engine),
            patch("src.services.document_service.get_db_connector", return_value=mock_connector),
            patch("src.services.document_service.check_ollama", return_value=llm_problem),
        ):
            resp = self.client.get("/api/v1/stats", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_stats_reports_ollama_model_and_status(self):
        data = self._stats(None)
        self.assertEqual(data["llm_backend"], "ollama")
        self.assertIn("llm_model", data)
        self.assertEqual(data["llm_status"], "ok")

    def test_stats_reports_llm_problem(self):
        data = self._stats("Ollama model 'qwen2.5:7b' is not pulled. Run: ollama pull qwen2.5:7b")
        self.assertIn("ollama pull", data["llm_status"])

    def test_query_concurrency_gate_allows_parallel_requests(self):
        async def run_concurrency_test():
            active_count = 0
            max_simultaneous = 0
            manager = QueryConcurrencyManager()

            async def worker():
                nonlocal active_count, max_simultaneous
                async with manager:
                    active_count += 1
                    max_simultaneous = max(max_simultaneous, active_count)
                    await asyncio.sleep(0.05)
                    active_count -= 1

            await asyncio.gather(worker(), worker(), worker())
            self.assertGreaterEqual(max_simultaneous, 2)

        asyncio.run(run_concurrency_test())


if __name__ == "__main__":
    unittest.main()
