"""Cancelling one's own requests (after confirmation) and adding information to them from the chat."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.agent.multi_agent.sub_agents.request_agent import ServiceRequestAgent, _request_id
from src.services.service_requests import ServiceRequestStore
from tests.agents.test_agent_collaboration import ScriptedLLM, StubAgent, build, step

AYSE = {"username": "ayse", "role": "viewer", "groups": []}


class TestRequestActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = ServiceRequestStore(db_path=os.path.join(self.tmp, "requests.db"))
        module = "src.agent.multi_agent.sub_agents.request_agent"
        for target, value in (
            (f"{module}.get_request_store", MagicMock(return_value=self.store)),
            (f"{module}.notify_new_request", MagicMock(return_value=False)),
            (f"{module}.audit_logger", MagicMock()),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mine = self.store.create("ayse", "it_support", "Projektör çalışmıyor")
        self.other = self.store.create("mehmet", "facilities", "Klima bozuk")

    def ask(self, question, request, thread="t1", plans=1):
        llm = ScriptedLLM(plans=[{"steps": [step("request_agent", "x")]}] * plans, request=request)
        self.orchestrator = getattr(self, "orchestrator", None) or build(
            llm, ServiceRequestAgent(), StubAgent("doc_agent")
        )
        self.orchestrator.supervisor._chat_model = llm
        for agent in self.orchestrator.registry.list_agents():
            agent.chat_model = llm
        return self.orchestrator.query(question, thread_id=thread, user=AYSE)

    def test_cancelling_needs_a_yes_and_only_works_on_ones_own_open_requests(self):
        cancel = {"action": "cancel", "request_id": self.mine["id"]}
        draft = self.ask(f"#{self.mine['id']} numaralı talebimi iptal et", cancel)
        self.assertIn("iptal etmemi onaylıyor musunuz", draft["answer"])
        self.assertEqual(self.store.get(self.mine["id"])["status"], "open")
        done = self.ask("evet", cancel)
        self.assertIn("iptal edildi", done["answer"])
        self.assertEqual(self.store.get(self.mine["id"])["status"], "cancelled")

        # Closed already, and another user's request is not even revealed
        self.assertIn("zaten kapatılmış", self.ask("talebimi iptal et", cancel, thread="t2")["answer"])
        other = self.ask("talebi iptal et", {"action": "cancel", "request_id": self.other["id"]}, thread="t3")
        self.assertIn("bulamadım", other["answer"])
        self.assertEqual(self.store.get(self.other["id"])["status"], "open")

    def test_without_a_number_the_only_open_request_is_meant(self):
        note = {"action": "note", "request_id": None, "note": "B204 dersliğinde, 2. kat."}
        answer = self.ask("Talebime ekle: B204 dersliğinde, 2. kat.", note)["answer"]
        self.assertIn(f"#{self.mine['id']}", answer)
        self.assertIn("B204 dersliğinde, 2. kat.", self.store.get(self.mine["id"])["description"])

        self.store.create("ayse", "other", "İkinci talep")
        which = self.ask("Talebime ekle: x y z", note, thread="t2")["answer"]
        self.assertIn("Hangi talebi kastediyorsunuz", which)
        self.assertIn("İkinci talep", which)

    def test_request_numbers_are_read_from_the_message(self):
        self.assertEqual(_request_id(None, "#12 numaralı talebim"), 12)
        self.assertEqual(_request_id(None, "7 nolu talebe ekle"), 7)
        self.assertEqual(_request_id("#5", ""), 5)
        self.assertIsNone(_request_id(None, "Talebimi iptal et"))


if __name__ == "__main__":
    unittest.main()
