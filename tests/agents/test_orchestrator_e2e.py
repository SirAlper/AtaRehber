"""End-to-end tests that execute the real compiled LangGraph workflow (no orchestrator mocks).

These cover multi-turn memory and forced routing, which unit tests with a mocked
orchestrator cannot detect (LangGraph silently drops state keys missing from the schema).
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
from src.agent.multi_agent.registry import AgentRegistry
from src.api.main import app
from src.auth.jwt_handler import create_access_token


class RecordingAgent(BaseSubAgent):
    """Sub-agent that records the state it receives and answers deterministically."""

    def __init__(self, name: str):
        super().__init__(chat_model=MagicMock())
        self.name = name
        self.display_name = f"{name} display"
        self.description = f"{name} test agent"
        self.seen_states = []

    def execute(self, state):
        self.seen_states.append(dict(state))
        turn = len(self.seen_states)
        return {
            "final_answer": f"{self.name} answer {turn}",
            "sources": [{"source": f"{self.name}.txt", "content": "chunk"}],
            "agent_trace": list(state.get("agent_trace", [])) + [{"agent": self.name, "action": "test"}],
        }


def routing_chat_model(target: str) -> MagicMock:
    """Chat model whose supervisor routing decision always selects `target`."""
    chat = MagicMock()
    chat.invoke.return_value = MagicMock(content=f'{{"agent": "{target}", "reason": "test", "direct_response": ""}}')
    return chat


class TestOrchestratorEndToEnd(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()
        self.alpha = RecordingAgent("alpha_agent")
        self.beta = RecordingAgent("beta_agent")
        self.registry.register(self.alpha)
        self.registry.register(self.beta)

    def _orchestrator(self, target="alpha_agent"):
        return MultiAgentOrchestrator(
            chat_model=routing_chat_model(target),
            registry=self.registry,
            checkpointer=MemorySaver(),
        )

    def test_chat_history_persists_across_turns(self):
        orch = self._orchestrator()
        first = orch.query("First question", thread_id="t1")
        second = orch.query("Second question", thread_id="t1")

        # The agent must see the previous turn on the second call
        self.assertEqual(self.alpha.seen_states[0].get("chat_history", []), [])
        history_seen = self.alpha.seen_states[1]["chat_history"]
        self.assertEqual(len(history_seen), 1)
        self.assertEqual(history_seen[0]["question"], "First question")
        self.assertEqual(history_seen[0]["answer"], first["answer"])

        self.assertEqual(
            [t["question"] for t in second["chat_history"]],
            ["First question", "Second question"],
        )

    def test_threads_are_isolated(self):
        orch = self._orchestrator()
        orch.query("Question in thread A", thread_id="a")
        result_b = orch.query("Question in thread B", thread_id="b")
        self.assertEqual(len(result_b["chat_history"]), 1)
        self.assertEqual(self.alpha.seen_states[1].get("chat_history", []), [])

    def test_history_is_trimmed(self):
        orch = self._orchestrator()
        with patch("src.agent.multi_agent.orchestrator_graph.CHAT_HISTORY_MAX_TURNS", 2):
            for i in range(4):
                result = orch.query(f"Question {i}", thread_id="trim")
        self.assertEqual(
            [t["question"] for t in result["chat_history"]],
            ["Question 2", "Question 3"],
        )

    def test_forced_agent_reaches_supervisor_through_graph(self):
        orch = self._orchestrator(target="alpha_agent")
        result = orch.query("Anything", thread_id="forced", forced_agent="beta_agent")

        self.assertEqual(result["active_agent"], "beta_agent")
        self.assertEqual(len(self.beta.seen_states), 1)
        self.assertEqual(len(self.alpha.seen_states), 0)
        orch.chat_model.invoke.assert_not_called()  # forced routing skips the LLM router

    def test_forced_agent_does_not_leak_into_next_turn(self):
        orch = self._orchestrator(target="alpha_agent")
        orch.query("Forced turn", thread_id="leak", forced_agent="beta_agent")
        result = orch.query("Auto turn", thread_id="leak")
        self.assertEqual(result["active_agent"], "alpha_agent")

    def test_query_without_thread_id(self):
        orch = self._orchestrator()
        result = orch.query("Stateless question")
        self.assertEqual(result["answer"], "alpha_agent answer 1")
        self.assertEqual(len(result["chat_history"]), 1)

    def test_greeting_is_recorded_in_history(self):
        orch = self._orchestrator()
        greeting = orch.query("Merhaba", thread_id="greet")
        self.assertEqual(greeting["active_agent"], "supervisor")
        result = orch.query("Real question", thread_id="greet")
        self.assertEqual(result["chat_history"][0]["agent"], "supervisor")

    def test_agents_registered_after_startup_are_routable(self):
        orch = self._orchestrator(target="late_agent")
        orch.query("Before registration", thread_id="late")
        late = RecordingAgent("late_agent")
        self.registry.register(late)

        result = orch.query("After registration", thread_id="late")
        self.assertEqual(result["active_agent"], "late_agent")
        self.assertEqual(result["answer"], "late_agent answer 1")
        # Recompiling kept the session history
        self.assertEqual([t["question"] for t in result["chat_history"]], ["Before registration", "After registration"])

    def test_unregistered_agent_is_no_longer_routed(self):
        orch = self._orchestrator(target="beta_agent")
        self.registry.unregister("beta_agent")
        with patch.object(orch.supervisor, "registry", self.registry):
            result = orch.query("Question", thread_id="gone", forced_agent="beta_agent")
        self.assertEqual(result["active_agent"], "supervisor")
        self.assertTrue(result["answer"])  # never an empty answer
        self.assertEqual(len(self.beta.seen_states), 0)

    def test_streaming_shares_memory_and_routing_with_query(self):
        orch = self._orchestrator()
        orch.query("Batch turn", thread_id="mixed")
        events = list(orch.stream_events("Streamed turn", thread_id="mixed", forced_agent="beta_agent"))

        selected = [e for e in events if e["type"] == "agent_selected"]
        self.assertEqual(selected[0]["agent"], "beta_agent")
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["active_agent"], "beta_agent")
        self.assertEqual(done["answer"], "beta_agent answer 1")
        # The streamed turn saw the batch turn and was itself persisted
        self.assertEqual(self.beta.seen_states[0]["chat_history"][0]["question"], "Batch turn")
        state = orch.app.get_state({"configurable": {"thread_id": "mixed"}})
        self.assertEqual(len(state.values["chat_history"]), 2)


class TestQueryApiEndToEnd(unittest.TestCase):
    """Drives /api/v1/query with a real orchestrator (only the LLM is stubbed)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        token, _ = create_access_token("admin", "admin")
        cls.headers = {"Authorization": f"Bearer {token}"}

    def setUp(self):
        self.registry = AgentRegistry()
        self.alpha = RecordingAgent("alpha_agent")
        self.beta = RecordingAgent("beta_agent")
        self.registry.register(self.alpha)
        self.registry.register(self.beta)
        self.orch = MultiAgentOrchestrator(
            chat_model=routing_chat_model("alpha_agent"),
            registry=self.registry,
            checkpointer=MemorySaver(),
        )
        patcher = patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=self.orch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_api_forced_agent_and_memory(self):
        r1 = self.client.post(
            "/api/v1/query",
            headers=self.headers,
            json={"question": "Q1", "session_id": "api_sess", "agent": "beta_agent"},
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r1.json()["active_agent"], "beta_agent")

        r2 = self.client.post(
            "/api/v1/query",
            headers=self.headers,
            json={"question": "Q2", "session_id": "api_sess"},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["active_agent"], "alpha_agent")
        self.assertEqual(self.alpha.seen_states[0]["chat_history"][0]["question"], "Q1")

    def test_api_stream_uses_same_graph(self):
        response = self.client.post(
            "/api/v1/query-stream",
            headers=self.headers,
            json={
                "question": "Streamed",
                "session_id": "stream_sess",
                "agent": "beta_agent",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"active_agent": "beta_agent"', response.text)

    def test_api_error_does_not_leak_exception_details(self):
        self.orch.query = MagicMock(side_effect=RuntimeError("secret connection string"))
        response = self.client.post("/api/v1/query", headers=self.headers, json={"question": "boom"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)


if __name__ == "__main__":
    unittest.main()
