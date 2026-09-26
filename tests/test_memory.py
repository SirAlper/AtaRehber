import unittest
from unittest.mock import MagicMock, patch
from langgraph.checkpoint.memory import MemorySaver

from src.agent.agent_graph import EnterpriseRAGAgent
from src.agent.prompts import build_rag_messages


class TestMultiTurnMemory(unittest.TestCase):
    def test_build_rag_messages_with_history(self):
        """Verify build_rag_messages formats previous conversation context."""
        history = [
            {
                "question": "What is our leave policy?",
                "answer": "Employees have 20 days.",
            },
            {"question": "How do I request it?", "answer": "Submit via the HR portal."},
        ]
        messages = build_rag_messages(
            context="Some HR documents.",
            question="Can I carry it over?",
            chat_history=history,
        )
        self.assertEqual(len(messages), 2)
        human_content = messages[1].content
        self.assertIn("Recent Conversation History:", human_content)
        self.assertIn("What is our leave policy?", human_content)
        self.assertIn("Can I carry it over?", human_content)

    @patch("src.agent.agent_graph.create_chat_model")
    def test_multi_turn_thread_isolation(self, mock_create_chat):
        """Verify thread_id preserves conversation state and isolates different users/sessions."""
        mock_engine = MagicMock()
        mock_engine.search.return_value = {
            "context": "Annual leave is 20 days per year.",
            "sources": [{"source": "hr.txt", "chunk_index": 0, "content": "20 days"}],
        }

        mock_chat = MagicMock()
        mock_create_chat.return_value = mock_chat

        # Use in-memory checkpointer for deterministic unit testing
        saver = MemorySaver()
        agent = EnterpriseRAGAgent(rag_engine=mock_engine, checkpointer=saver)

        # Mock responses
        mock_response_1 = MagicMock()
        mock_response_1.content = "Annual leave is 20 days."

        mock_grader = MagicMock()
        mock_grader.content = "yes"

        mock_chat.invoke.side_effect = [mock_response_1, mock_grader]

        # Turn 1 in thread_alpha
        res1 = agent.query("How many days of leave do I get?", thread_id="thread_alpha")
        self.assertIn("Annual leave is 20 days", res1["answer"])
        self.assertEqual(len(res1.get("chat_history", [])), 1)

        # Turn 2 in thread_alpha: verify history accumulated (rewrite + generate + grade)
        mock_rewrite = MagicMock()
        mock_rewrite.content = "HR portal leave application submission process"
        mock_response_2 = MagicMock()
        mock_response_2.content = "Submit via HR portal."
        mock_chat.invoke.side_effect = [mock_rewrite, mock_response_2, mock_grader]

        res2 = agent.query("Where do I apply?", thread_id="thread_alpha")
        self.assertEqual(len(res2.get("chat_history", [])), 2)
        self.assertEqual(res2["chat_history"][0]["question"], "How many days of leave do I get?")
        self.assertEqual(res2["chat_history"][1]["question"], "Where do I apply?")

        # Turn 1 in different thread_beta: should start with empty prior history
        mock_response_beta = MagicMock()
        mock_response_beta.content = "Company budget is 5M."
        mock_chat.invoke.side_effect = [mock_response_beta, mock_grader]

        res_beta = agent.query("What is the budget?", thread_id="thread_beta")
        self.assertEqual(len(res_beta.get("chat_history", [])), 1)
        self.assertEqual(res_beta["chat_history"][0]["question"], "What is the budget?")


if __name__ == "__main__":
    unittest.main()
