import unittest
from src.agent.nodes import AgentNodes


class TestAgentGraphDecision(unittest.TestCase):
    """Tests for LangGraph conditional edge routing and self-RAG retry logic."""

    def test_decide_hallucinate_pass_english(self):
        state = {
            "hallucination_grade": "yes, the answer is fully supported",
            "retry_count": 0,
        }
        decision = AgentNodes.decide_hallucinate(state)
        self.assertEqual(decision, "end")

    def test_decide_hallucinate_pass_turkish(self):
        state = {"hallucination_grade": "evet, belgelerle tutarlıdır", "retry_count": 0}
        decision = AgentNodes.decide_hallucinate(state)
        self.assertEqual(decision, "end")

    def test_decide_hallucinate_route_to_refine_on_first_failure(self):
        state = {
            "hallucination_grade": "no, there are unsupported claims",
            "retry_count": 0,
        }
        decision = AgentNodes.decide_hallucinate(state)
        self.assertEqual(decision, "refine")

    def test_decide_hallucinate_route_to_fallback_on_second_failure(self):
        state = {"hallucination_grade": "hayır, cevap doğrulanamadı", "retry_count": 1}
        decision = AgentNodes.decide_hallucinate(state)
        self.assertEqual(decision, "fallback")

    def test_decide_hallucinate_pass_after_refine(self):
        # Even if retry_count is 1, if it passed the second grade, it must return "end"
        state = {
            "hallucination_grade": "yes, now the refined answer is grounded in context",
            "retry_count": 1,
        }
        decision = AgentNodes.decide_hallucinate(state)
        self.assertEqual(decision, "end")


if __name__ == "__main__":
    unittest.main()
