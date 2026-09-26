import asyncio
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.state import QueryConcurrencyManager
from src.auth.jwt_handler import create_access_token


class TestLLMBackendAndConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        token, _ = create_access_token("admin", "admin")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    def test_stats_reports_llm_backend(self):
        """Verify /api/v1/stats reports active llm_backend and model."""
        mock_engine = MagicMock()
        mock_engine.get_stats.return_value = {
            "total_chunks": 0,
            "total_documents": 0,
            "document_chunks": {},
        }
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = {"status": "not_configured"}
        with (
            patch("src.services.document_service.get_rag_engine", return_value=mock_engine),
            patch(
                "src.services.document_service.get_db_connector",
                return_value=mock_connector,
            ),
        ):
            resp = self.client.get("/api/v1/stats", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("llm_backend", data)
        self.assertIn(data["llm_backend"], ["huggingface", "ollama"])
        self.assertIn("llm_model", data)

    def test_create_chat_model_ollama_branch(self):
        """Verify create_chat_model returns ChatOllama when LLM_BACKEND is ollama."""
        with patch("src.agent.llm.LLM_BACKEND", "ollama"):
            with patch("src.agent.llm.OLLAMA_BASE_URL", "http://127.0.0.1:11434"):
                with patch("src.agent.llm.OLLAMA_MODEL", "qwen2.5:7b"):
                    from src.agent.llm import create_chat_model
                    from langchain_ollama import ChatOllama

                    model = create_chat_model()
                    self.assertIsInstance(model, ChatOllama)
                    self.assertEqual(model.model, "qwen2.5:7b")

    def test_query_concurrency_gate_parallelism(self):
        """Verify QueryConcurrencyManager permits parallel entry in ollama mode."""

        async def run_concurrency_test():
            active_count = 0
            max_simultaneous = 0

            manager = QueryConcurrencyManager()

            async def worker():
                nonlocal active_count, max_simultaneous
                async with manager:
                    active_count += 1
                    if active_count > max_simultaneous:
                        max_simultaneous = active_count
                    await asyncio.sleep(0.05)
                    active_count -= 1

            # In ollama mode, 3 tasks should run concurrently
            with patch("src.api.state.LLM_BACKEND", "ollama"):
                await asyncio.gather(worker(), worker(), worker())
            self.assertGreaterEqual(max_simultaneous, 2)

        asyncio.run(run_concurrency_test())


if __name__ == "__main__":
    unittest.main()
