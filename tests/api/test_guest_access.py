"""Guest access: visitors without an account ask doc_agent about documents shared with the visitor group."""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api import main as api_main
from src.api import state as api_state
from src.api.main import app
from src.agent.language import message
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.auth.jwt_handler import create_access_token


def answer(text="Kayıt yenileme Eylül ayında yapılır."):
    orchestrator = MagicMock()
    orchestrator.query.return_value = {"answer": text, "sources": [], "active_agent": "doc_agent", "agents": []}
    return orchestrator


class TestGuestSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def setUp(self):
        api_main._rate_limit_store.clear()
        self.addCleanup(api_main._rate_limit_store.clear)

    def guest_headers(self):
        response = self.client.post("/api/v1/auth/guest")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["role"], "guest")
        self.assertTrue(data["username"].startswith("guest-"))
        self.assertIsNone(data["refresh_token"])
        return {"Authorization": f"Bearer {data['access_token']}"}

    def test_disabled_by_default(self):
        self.assertEqual(self.client.get("/api/v1/auth/guest").json(), {"enabled": False})
        self.assertEqual(self.client.post("/api/v1/auth/guest").status_code, 404)

    def test_guest_questions_go_to_doc_agent_and_nothing_else_is_allowed(self):
        with patch("src.core.config.GUEST_ACCESS_ENABLED", True):
            self.assertEqual(self.client.get("/api/v1/auth/guest").json(), {"enabled": True})
            headers = self.guest_headers()
            orchestrator = answer()
            with patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=orchestrator):
                # Even when the client asks for another agent
                response = self.client.post(
                    "/api/v1/query", headers=headers, json={"question": "Kayıt ne zaman?", "agent": "request_agent"}
                )
            self.assertEqual(response.status_code, 200, response.text)
            kwargs = orchestrator.query.call_args.kwargs
            self.assertEqual(kwargs["forced_agent"], "doc_agent")
            self.assertEqual(kwargs["user"]["role"], "guest")
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).json()["role"], "guest")
            for method, path in (
                ("get", "/api/v1/documents"),
                ("get", "/api/v1/requests"),
                ("get", "/api/v1/agents"),
                ("get", "/api/v1/stats"),
                ("get", "/api/v1/admin/audit-logs"),
                ("post", "/api/v1/auth/change-password"),
            ):
                kwargs = {"json": {"current_password": "x", "new_password": "y"}} if method == "post" else {}
                response = getattr(self.client, method)(path, headers=headers, **kwargs)
                self.assertEqual(response.status_code, 403, f"{path}: {response.status_code}")

    def test_turning_guest_access_off_ends_guest_sessions(self):
        token, _ = create_access_token("guest-abc", "guest")
        response = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    def test_guest_sessions_have_their_own_question_budget(self):
        with (
            patch("src.core.config.GUEST_ACCESS_ENABLED", True),
            patch("src.api.main.GUEST_RATE_LIMIT_PER_MINUTE", 2),
            patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=answer()),
        ):
            first, second = self.guest_headers(), self.guest_headers()
            for _ in range(2):
                self.assertEqual(
                    self.client.post("/api/v1/query", headers=first, json={"question": "q"}).status_code, 200
                )
            self.assertEqual(self.client.post("/api/v1/query", headers=first, json={"question": "q"}).status_code, 429)
            # Another visitor behind the same IP is not affected
            self.assertEqual(self.client.post("/api/v1/query", headers=second, json={"question": "q"}).status_code, 200)

    def test_accounts_cannot_be_created_with_the_guest_role(self):
        token, _ = create_access_token("admin", "admin")
        response = self.client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={"username": "fake_guest", "password": "Passw0rdX!", "role": "guest"},
        )
        self.assertEqual(response.status_code, 422)


class TestQueueLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_full_queue_answers_busy_at_once(self):
        token, _ = create_access_token("admin", "admin")
        headers = {"Authorization": f"Bearer {token}"}
        with (
            patch.object(api_state.query_concurrency_gate, "is_full", return_value=True),
            patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=answer()) as get_orchestrator,
        ):
            for path in ("/api/v1/query", "/api/v1/query-stream"):
                response = self.client.post(path, headers=headers, json={"question": "q"})
                self.assertEqual(response.status_code, 503, path)
                self.assertIn("busy", response.json()["detail"])
                self.assertEqual(response.headers["Retry-After"], "60")
        get_orchestrator.return_value.query.assert_not_called()

    def test_gate_rejects_only_beyond_the_waiting_limit(self):
        gate = api_state.QueryConcurrencyManager()
        semaphore = asyncio.Semaphore(1)

        async def scenario():
            with patch.object(api_state, "ollama_semaphore", semaphore), patch("src.core.config.MAX_QUEUED_QUERIES", 1):
                await gate.__aenter__()  # runs
                waiter = asyncio.ensure_future(gate.__aenter__())  # waits (1 allowed)
                await asyncio.sleep(0)
                self.assertEqual(gate.waiting, 1)
                with self.assertRaises(api_state.QueueFullError):
                    await gate.__aenter__()
                await gate.__aexit__(None, None, None)
                await waiter
                await gate.__aexit__(None, None, None)
                self.assertEqual(gate.waiting, 0)

        asyncio.run(scenario())


class TestGuestGreeting(unittest.TestCase):
    def route(self, question, role):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=AgentRegistry())
        supervisor.registry.get = lambda name: object()
        return supervisor.route({"question": question, "forced_agent": "doc_agent", "user": {"role": role}})

    def test_a_greeting_is_answered_even_with_a_forced_agent(self):
        self.assertEqual(self.route("Merhaba", "guest")["final_answer"], message("greeting_guest", "tr"))
        self.assertEqual(self.route("Merhaba", "viewer")["final_answer"], message("greeting", "tr"))
        self.assertEqual(self.route("Kayıt ne zaman yapılır?", "guest")["next_agent"], "doc_agent")


if __name__ == "__main__":
    unittest.main()
