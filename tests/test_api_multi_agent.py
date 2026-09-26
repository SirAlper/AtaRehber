import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator


class TestAPIMultiAgentIntegration(unittest.TestCase):
    """Integration tests for Multi-Agent API endpoints: /api/v1/agents and /api/v1/query."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        token, _ = create_access_token("admin", "admin")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    def test_list_agents_unauthorized(self):
        """Endpoints must reject unauthenticated requests with 401."""
        response = self.client.get("/api/v1/agents")
        self.assertEqual(response.status_code, 401)

    def test_list_agents_authorized(self):
        """Authenticated users should receive list of all registered sub-agents + auto."""
        response = self.client.get("/api/v1/agents", headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("agents", data)
        agents = data["agents"]
        agent_names = [a["name"] for a in agents]

        # Verify default orchestrator option exists
        self.assertIn("auto", agent_names)
        # Verify core sub-agents exist
        self.assertIn("doc_agent", agent_names)
        self.assertIn("db_agent", agent_names)
        self.assertIn("compliance_agent", agent_names)

        # Check structure of agent metadata
        doc_agent_meta = next(a for a in agents if a["name"] == "doc_agent")
        self.assertTrue(len(doc_agent_meta["display_name"]) > 0)
        self.assertTrue(len(doc_agent_meta["description"]) > 0)
        self.assertTrue(len(doc_agent_meta["version"]) > 0)

    def test_query_direct_greeting_supervisor(self):
        """Greetings should be routed directly by Supervisor without calling worker sub-agents."""
        mock_chat = MagicMock()
        orchestrator = MultiAgentOrchestrator(chat_model=mock_chat, checkpointer=MemorySaver())
        with patch(
            "src.api.routes.query.get_multi_agent_orchestrator",
            return_value=orchestrator,
        ):
            response = self.client.post(
                "/api/v1/query",
                headers=self.auth_headers,
                json={"question": "Merhaba, nasılsın?", "session_id": "test_session_1"},
            )
        mock_chat.invoke.assert_not_called()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["active_agent"], "supervisor")
        self.assertTrue(len(data["answer"]) > 0)
        self.assertIsInstance(data["agent_trace"], list)
        self.assertIsInstance(data["sources"], list)

    def test_query_forced_agent(self):
        """Specifying an explicit agent should route to that agent."""
        mock_response = {
            "answer": "Denetim raporu: Herhangi bir uyumsuzluk tespit edilmedi.",
            "sources": [],
            "agent_trace": [
                {
                    "agent": "compliance_agent",
                    "action": "audit",
                    "duration_ms": 150,
                    "status": "success",
                }
            ],
            "active_agent": "compliance_agent",
            "chat_history": [],
        }

        with patch("src.api.routes.query.get_multi_agent_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.query.return_value = mock_response
            mock_get_orch.return_value = mock_orch

            response = self.client.post(
                "/api/v1/query",
                headers=self.auth_headers,
                json={
                    "question": "Hediye kabul politikamız nedir?",
                    "agent": "compliance_agent",
                    "session_id": "test_session_compliance",
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["active_agent"], "compliance_agent")
            self.assertIn("Denetim raporu", data["answer"])
            mock_orch.query.assert_called_once()
            call_kwargs = mock_orch.query.call_args[1]
            self.assertEqual(call_kwargs["forced_agent"], "compliance_agent")

    def test_query_stream_endpoint(self):
        """Streaming endpoint should deliver NDJSON formatted events."""
        events_to_stream = [
            {
                "type": "status",
                "message": "Supervisor routing...",
                "node": "supervisor",
            },
            {
                "type": "agent_selected",
                "agent": "doc_agent",
                "display_name": "Belge RAG",
                "reason": "Doküman araması",
            },
            {
                "type": "done",
                "answer": "Cevap metni",
                "sources": [],
                "agent_trace": [],
                "active_agent": "doc_agent",
            },
        ]

        with patch("src.api.routes.query.get_multi_agent_orchestrator") as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.stream_events.return_value = iter(events_to_stream)
            mock_get_orch.return_value = mock_orch

            response = self.client.post(
                "/api/v1/query-stream",
                headers=self.auth_headers,
                json={"question": "Yıllık izin kaç gündür?", "agent": "doc_agent"},
            )

            self.assertEqual(response.status_code, 200)
            lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
            self.assertEqual(len(lines), 3)
            self.assertIn("Supervisor routing...", lines[0])
            self.assertIn("doc_agent", lines[1])
            self.assertIn("Cevap metni", lines[2])


if __name__ == "__main__":
    unittest.main()
