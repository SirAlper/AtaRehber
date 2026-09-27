import unittest
from unittest.mock import MagicMock
from langgraph.checkpoint.memory import MemorySaver

from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.state import AgentResponse
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator


class MockSubAgent(BaseSubAgent):
    name = "mock_agent"
    display_name = "Mock Test Ajanı"
    description = "Test amaçlı sahte alt ajan"

    def execute(self, state):
        return {
            "final_answer": "Mock ajan yanıtı",
            "sources": [{"source": "test.txt", "content": "test chunk"}],
            "agent_trace": list(state.get("agent_trace", []))
            + [
                {
                    "agent": self.name,
                    "action": "mock_execution",
                    "status": "success",
                }
            ],
        }


class TestMultiAgentCore(unittest.TestCase):
    """Test suite for MultiAgent State, BaseSubAgent, and AgentRegistry."""

    def setUp(self):
        self.registry = AgentRegistry()

    def test_agent_registration_and_lookup(self):
        agent = MockSubAgent()
        self.registry.register(agent)

        self.assertIn("mock_agent", self.registry.list_agent_names())
        fetched = self.registry.get("mock_agent")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.display_name, "Mock Test Ajanı")

    def test_register_agent_class(self):
        self.registry.register(MockSubAgent)
        self.assertIn("mock_agent", self.registry.list_agent_names())

    def test_invalid_agent_rejection(self):
        class NonAgent:
            pass

        with self.assertRaises(TypeError):
            self.registry.register(NonAgent)

    def test_empty_name_rejection(self):
        class BadAgent(BaseSubAgent):
            name = ""
            description = "bad"

            def execute(self, state):
                pass

        with self.assertRaises(ValueError):
            self.registry.register(BadAgent)

    def test_supervisor_prompt_generation(self):
        agent = MockSubAgent()
        self.registry.register(agent)

        prompt = self.registry.get_supervisor_prompt()
        self.assertIn("mock_agent", prompt)
        self.assertIn("Mock Test Ajanı", prompt)
        self.assertIn("Test amaçlı sahte alt ajan", prompt)

    def test_unregister_agent(self):
        agent = MockSubAgent()
        self.registry.register(agent)
        self.assertTrue(self.registry.unregister("mock_agent"))
        self.assertIsNone(self.registry.get("mock_agent"))
        self.assertFalse(self.registry.unregister("non_existent"))

    def test_agent_response_model(self):
        resp = AgentResponse(content="Başarılı yanıt", sources=[{"source": "doc.pdf"}])
        self.assertEqual(resp.content, "Başarılı yanıt")
        self.assertEqual(len(resp.sources), 1)
        self.assertEqual(resp.metadata, {})


class TestSupervisorAndOrchestrator(unittest.TestCase):
    """Test suite for Supervisor routing and Orchestrator LangGraph workflow."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.mock_agent = MockSubAgent()
        self.registry.register(self.mock_agent)

    def test_supervisor_direct_greeting(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=self.registry)
        result = supervisor.route({"question": "Hello"})

        self.assertEqual(result["next_agent"], "finish")
        self.assertIn("Hello!", result["final_answer"])
        self.assertEqual(len(result["agent_trace"]), 1)
        self.assertEqual(result["agent_trace"][0]["action"], "direct_greeting")

    def test_supervisor_forced_agent(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=self.registry)
        result = supervisor.route({"question": "Rastgele soru", "forced_agent": "mock_agent"})

        self.assertEqual(result["next_agent"], "mock_agent")

    def test_supervisor_heuristic_fallback(self):
        for name in ("db_agent", "compliance_agent", "request_agent"):
            self.registry.register(type(f"Stub_{name}", (MockSubAgent,), {"name": name})())
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=self.registry)

        target, _ = supervisor._heuristic_routing("Hangi ürünün stok miktarı daha fazla?")
        self.assertEqual(target, "db_agent")

        target, _ = supervisor._heuristic_routing("Bu talep şirket güvenlik politikasına uygun mu?")
        self.assertEqual(target, "compliance_agent")

        target, _ = supervisor._heuristic_routing("Projektör bozuk, arıza kaydı açar mısın?")
        self.assertEqual(target, "request_agent")

        target, _ = supervisor._heuristic_routing("Genel şirket bilgisi")
        self.assertEqual(target, "doc_agent")

    def test_heuristic_fallback_skips_unavailable_agents(self):
        class OfflineDb(MockSubAgent):
            name = "db_agent"

            def is_available(self):
                return False

        self.registry.register(OfflineDb())
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=self.registry)
        target, _ = supervisor._heuristic_routing("Hangi ürünün stok miktarı daha fazla?")
        self.assertEqual(target, "doc_agent")

    def test_orchestrator_graph_compilation_and_execution(self):
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = MagicMock(content='{"agent": "mock_agent", "reason": "Test delegation"}')

        orchestrator = MultiAgentOrchestrator(
            chat_model=mock_chat,
            registry=self.registry,
            checkpointer=MemorySaver(),
        )

        result = orchestrator.query("Mock bir soru soruyorum", thread_id="test_thread")

        self.assertEqual(result["answer"], "Mock ajan yanıtı")
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["active_agent"], "mock_agent")
        self.assertTrue(len(result["agent_trace"]) >= 2)  # supervisor + mock_agent

    def test_orchestrator_streaming_events(self):
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = MagicMock(content='{"agent": "mock_agent", "reason": "Stream test"}')

        orchestrator = MultiAgentOrchestrator(
            chat_model=mock_chat,
            registry=self.registry,
            checkpointer=MemorySaver(),
        )

        events = list(orchestrator.stream_events("Stream soru", thread_id="test_stream"))
        event_types = [e["type"] for e in events]

        self.assertIn("status", event_types)
        self.assertIn("agent_selected", event_types)
        self.assertIn("sources", event_types)
        self.assertIn("done", event_types)

        done_event = [e for e in events if e["type"] == "done"][0]
        self.assertEqual(done_event["answer"], "Mock ajan yanıtı")


if __name__ == "__main__":
    unittest.main()
