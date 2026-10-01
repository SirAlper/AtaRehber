"""Per-agent statistics from the audit log, and feedback that names the rated agent."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.audit import audit_logger
from src.services.agent_stats import agent_stats
from src.services.review import question_of
from tests.api.test_access_and_requests import ensure_user


class TestAgentStats(unittest.TestCase):
    def test_answers_and_ratings_are_counted_per_agent(self):
        agent = f"stats_{uuid.uuid4().hex[:8]}"
        for status, duration in (("success", 1000), ("success", 3000), ("warning", 2000), ("error", 9000)):
            audit_logger.log(
                username="u",
                role="viewer",
                action="query_stream",
                detail=f"[{agent}] Soru?",
                status=status,
                duration_ms=duration,
            )
        client = TestClient(app)
        viewer = ensure_user("stats_viewer", "viewer")
        for rating in ("negative", "negative", "positive"):
            response = client.post(
                "/api/v1/feedback", headers=viewer, json={"question": "Soru?", "feedback": rating, "agent": agent}
            )
            self.assertEqual(response.status_code, 200, response.text)
        # The rated answer's question is still found for the review list
        negative = asyncio.run(audit_logger.aquery_logs(action="feedback", limit=1))[0]
        self.assertEqual(question_of(negative["detail"]), "Soru?")

        row = next(a for a in asyncio.run(agent_stats(30))["agents"] if a["agent"] == agent)
        self.assertEqual((row["questions"], row["warnings"], row["errors"]), (4, 1, 1))
        self.assertEqual((row["positive"], row["negative"]), (1, 2))
        self.assertEqual((row["median_ms"], row["p90_ms"]), (3000, 9000))
        self.assertEqual(row["warning_rate"], 0.25)

    def test_only_admins_see_the_statistics_and_agent_names_are_checked(self):
        client = TestClient(app)
        viewer = ensure_user("stats_viewer", "viewer")
        self.assertEqual(client.get("/api/v1/admin/agent-stats", headers=viewer).status_code, 403)
        admin = ensure_user("stats_admin", "admin")
        self.assertEqual(client.get("/api/v1/admin/agent-stats?days=7", headers=admin).json()["days"], 7)
        bad = client.post("/api/v1/feedback", headers=viewer, json={"feedback": "positive", "agent": "[x] y"})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
