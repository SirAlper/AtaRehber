"""Agent collaboration: plans with several agents, handoffs, answer synthesis, and confirmed service requests."""

import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langgraph.checkpoint.memory import MemorySaver

from src.agent.language import confirmation_reply
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.orchestrator_graph import MULTI_AGENT, MultiAgentOrchestrator
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.request_agent import ServiceRequestAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.services.service_requests import ServiceRequestStore

REQUEST_DRAFT = {"action": "create", "category": "it_support", "title": "Projektör çalışmıyor", "description": "B204"}


class ScriptedLLM:
    """Chat model with scripted replies per prompt type; unexpected prompts fail the test."""

    def __init__(self, plans=(), synthesis="COMBINED", grade="yes", request=None):
        self.plans = list(plans)
        self.synthesis = synthesis
        self.grade = grade
        self.request = request or REQUEST_DRAFT
        self.request_inputs = []

    def invoke(self, messages):
        system = messages[0].content
        if "supervisor of an AI assistant team" in system:
            return SimpleNamespace(content=json.dumps(self.plans.pop(0)))
        if "combine the partial answers" in system:
            return SimpleNamespace(content=self.synthesis)
        if "factual auditor" in system:
            return SimpleNamespace(content=self.grade)
        if "service request" in system:
            self.request_inputs.append(messages[-1].content)
            return SimpleNamespace(content=json.dumps(self.request))
        raise AssertionError(f"unexpected prompt: {system[:80]}")


class StubAgent(BaseSubAgent):
    def __init__(self, name, answer=None, status="success", available=True, handoff_on=None, grade="", output=None):
        super().__init__(chat_model=MagicMock())
        self.name = name
        self.display_name = name.upper()
        self.description = f"{name} stub"
        self.handoff_on = handoff_on or {}
        self._answer = answer or f"{name} answer"
        self._status = status
        self._available = available
        self._grade = grade
        self._output = output or {}
        self.questions = []

    def is_available(self):
        return self._available

    def execute(self, state):
        self.questions.append(state["question"])
        out = {
            "final_answer": self._answer,
            "sources": [{"source": f"{self.name}.txt", "chunk_index": 0, "content": self.name}],
            "agent_trace": list(state.get("agent_trace", []))
            + [{"agent": self.name, "action": "stub", "status": self._status}],
            **self._output,
        }
        if self._grade:
            out["hallucination_grade"] = self._grade
        return out


def step(agent, question):
    return {"agent": agent, "question": question}


def build(llm, *agents):
    registry = AgentRegistry()
    for agent in agents:
        registry.register(agent)
    return MultiAgentOrchestrator(chat_model=llm, registry=registry, checkpointer=MemorySaver())


def actions(result):
    return [entry.get("action") for entry in result["agent_trace"]]


class TestPlansAndSynthesis(unittest.TestCase):
    def test_composite_question_runs_each_agent_on_its_sub_question_and_combines(self):
        doc, db = StubAgent("doc_agent"), StubAgent("db_agent")
        llm = ScriptedLLM(plans=[{"steps": [step("doc_agent", "Kural ne?"), step("db_agent", "Kaç tane?")]}])
        result = build(llm, doc, db).query("Kural ne ve kaç tane?")

        self.assertEqual(doc.questions, ["Kural ne?"])
        self.assertEqual(db.questions, ["Kaç tane?"])
        self.assertEqual(result["active_agent"], MULTI_AGENT)
        self.assertEqual(result["agents"], ["doc_agent", "db_agent"])
        self.assertEqual(result["answer"], "COMBINED")
        self.assertEqual({s["source"] for s in result["sources"]}, {"doc_agent.txt", "db_agent.txt"})
        self.assertEqual(actions(result)[-1], "synthesize")

    def test_combined_answer_not_supported_by_the_parts_falls_back_to_the_parts(self):
        doc, db = StubAgent("doc_agent", answer="20 gün"), StubAgent("db_agent", answer="5 kayıt")
        llm = ScriptedLLM(plans=[{"steps": [step("doc_agent", "a"), step("db_agent", "b")]}], grade="no")
        result = build(llm, doc, db).query("a ve b")

        self.assertNotEqual(result["answer"], "COMBINED")
        self.assertIn("20 gün", result["answer"])
        self.assertIn("5 kayıt", result["answer"])
        self.assertEqual(result["agent_trace"][-1]["status"], "unverified")

    def test_combined_answer_is_verified_only_if_every_part_is(self):
        doc = StubAgent("doc_agent", grade="yes")
        compliance = StubAgent("compliance_agent", grade="no")
        llm = ScriptedLLM(plans=[{"steps": [step("doc_agent", "a"), step("compliance_agent", "b")]}])
        result = build(llm, doc, compliance).query("a ve b")
        self.assertEqual(result["hallucination_grade"], "no")

    def test_single_step_keeps_the_agent_and_its_grade(self):
        doc = StubAgent("doc_agent", grade="yes")
        result = build(ScriptedLLM(plans=[{"steps": [step("doc_agent", "shortened")]}]), doc).query("Tam soru?")
        self.assertEqual(result["active_agent"], "doc_agent")
        self.assertEqual(result["hallucination_grade"], "yes")
        self.assertEqual(doc.questions, ["Tam soru?"])  # a single step answers the user's own question


class TestHandoffs(unittest.TestCase):
    def test_failed_step_is_handed_to_the_mapped_agent(self):
        db = StubAgent("db_agent", status="rejected", handoff_on={"rejected": "doc_agent"})
        doc = StubAgent("doc_agent", answer="Kurul 21 üyeden oluşur.")
        result = build(ScriptedLLM(plans=[{"steps": [step("db_agent", "YÖK kaç üyeden oluşur?")]}]), db, doc).query(
            "YÖK kaç üyeden oluşur?"
        )

        self.assertEqual(result["active_agent"], "doc_agent")
        self.assertEqual(result["agents"], ["doc_agent"])
        self.assertEqual(result["answer"], "Kurul 21 üyeden oluşur.")
        self.assertEqual(doc.questions, ["YÖK kaç üyeden oluşur?"])
        handoff = next(e for e in result["agent_trace"] if e.get("action") == "handoff")
        self.assertEqual((handoff["from_agent"], handoff["target_agent"]), ("db_agent", "doc_agent"))

    def test_handoffs_do_not_loop(self):
        db = StubAgent("db_agent", status="rejected", handoff_on={"rejected": "doc_agent"})
        doc = StubAgent("doc_agent", status="no_context", handoff_on={"no_context": "db_agent"})
        result = build(ScriptedLLM(plans=[{"steps": [step("db_agent", "q")]}]), db, doc).query("q")
        self.assertEqual(len(db.questions), 1)
        self.assertEqual(len(doc.questions), 1)
        self.assertEqual(result["active_agent"], "doc_agent")

    def test_no_handoff_to_an_unavailable_agent(self):
        db = StubAgent("db_agent", answer="query rejected", status="rejected", handoff_on={"rejected": "doc_agent"})
        doc = StubAgent("doc_agent", available=False)
        result = build(ScriptedLLM(plans=[{"steps": [step("db_agent", "q")]}]), db, doc).query("q", forced_agent=None)
        self.assertEqual(result["answer"], "query rejected")
        self.assertEqual(doc.questions, [])

    def test_agent_can_request_a_handoff(self):
        custom = StubAgent("custom_agent", output={"handoff": {"to": "doc_agent", "reason": "not my domain"}})
        doc = StubAgent("doc_agent")
        result = build(ScriptedLLM(plans=[{"steps": [step("custom_agent", "q")]}]), custom, doc).query("q")
        self.assertEqual(result["active_agent"], "doc_agent")
        self.assertIn("not my domain", next(e["reason"] for e in result["agent_trace"] if e.get("action") == "handoff"))

    def test_stream_reports_the_handoff(self):
        db = StubAgent("db_agent", status="rejected", handoff_on={"rejected": "doc_agent"})
        orchestrator = build(ScriptedLLM(plans=[{"steps": [step("db_agent", "q")]}]), db, StubAgent("doc_agent"))
        events = list(orchestrator.stream_events("q"))
        handoff = next(e for e in events if e["type"] == "handoff")
        self.assertEqual((handoff["from"], handoff["to"]), ("db_agent", "doc_agent"))
        self.assertEqual(events[-1]["active_agent"], "doc_agent")


class TestSupervisorPlans(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()
        for agent in (StubAgent("doc_agent"), StubAgent("db_agent", available=False), StubAgent("compliance_agent")):
            self.registry.register(agent)

    def route(self, reply, question="soru", max_steps=3):
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content=json.dumps(reply))
        return SupervisorAgent(chat_model=llm, registry=self.registry, max_steps=max_steps).route(
            {"question": question}
        )

    def test_unavailable_and_unknown_agents_fall_back_to_doc_agent_and_duplicates_are_dropped(self):
        decision = self.route(
            {"steps": [step("db_agent", "a"), step("unknown", "a"), step("compliance_agent", "b")]}, max_steps=3
        )
        self.assertEqual([s["agent"] for s in decision["plan"]], ["doc_agent", "compliance_agent"])

    def test_plan_is_capped(self):
        decision = self.route({"steps": [step("doc_agent", "a"), step("compliance_agent", "b")]}, max_steps=1)
        self.assertEqual(len(decision["plan"]), 1)

    def test_sub_questions_for_the_same_agent_become_one_step(self):
        steps = [step("doc_agent", "Ders bırakma süresi?"), step("doc_agent", "Kayıt yenileme ne zaman biter?")]
        decision = self.route({"steps": steps}, question="Dersler ne kadar süre içinde bırakılabilir?")
        self.assertEqual(decision["plan"], [step("doc_agent", "Dersler ne kadar süre içinde bırakılabilir?")])

    def test_older_single_agent_format_is_accepted(self):
        decision = self.route({"agent": "compliance_agent", "reason": "r"}, question="Uygun mu?")
        self.assertEqual(decision["plan"], [step("compliance_agent", "Uygun mu?")])

    def test_empty_plan_answers_directly(self):
        decision = self.route({"steps": [], "direct_response": "Merhaba!"})
        self.assertEqual((decision["next_agent"], decision["final_answer"]), ("finish", "Merhaba!"))

    def test_unavailable_agents_are_not_offered(self):
        prompt = self.registry.get_supervisor_prompt()
        self.assertNotIn("db_agent", prompt)
        self.assertIn("compliance_agent", prompt)
        self.assertEqual([a.name for a in self.registry.list_available_agents()], ["doc_agent", "compliance_agent"])


class TestConfirmationReplies(unittest.TestCase):
    def test_short_yes_and_no_answers(self):
        for text in ("Evet", "evet, oluştur", "Onaylıyorum", "yes", "OK"):
            self.assertEqual(confirmation_reply(text), "confirm", text)
        for text in ("Hayır", "iptal", "vazgeç", "no", "cancel"):
            self.assertEqual(confirmation_reply(text), "reject", text)

    def test_other_messages_are_not_answers(self):
        for text in ("Yıllık izin kaç gün?", "evet ama önce şunu sorayım, izin kaç gün sürer?", ""):
            self.assertIsNone(confirmation_reply(text), text)


class TestServiceRequestFlow(unittest.TestCase):
    user = {"username": "ayse", "role": "viewer", "groups": []}

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

    def orchestrator(self, plans):
        self.llm = ScriptedLLM(plans=plans)
        return build(self.llm, ServiceRequestAgent(), StubAgent("doc_agent"))

    def test_request_is_drafted_and_filed_only_after_confirmation(self):
        orchestrator = self.orchestrator([{"steps": [step("request_agent", "x")]}])
        first = orchestrator.query("B204'te projektör bozuk, arıza kaydı aç", thread_id="t1", user=self.user)
        self.assertIn("onaylıyor musunuz", first["answer"])
        # The category by name, not the internal key
        self.assertIn("**Kategori:** Bilgi İşlem", first["answer"])
        self.assertNotIn("it_support", first["answer"])
        self.assertEqual(self.store.list(), [])

        second = orchestrator.query("Evet", thread_id="t1", user=self.user)  # no routing LLM call needed
        records = self.store.list()
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["username"], records[0]["category"]), ("ayse", "it_support"))
        self.assertIn(f"#{records[0]['id']}", second["answer"])
        self.assertIn("confirmation_routing", actions(second))

        # The draft is used once: another "evet" is routed normally and files nothing
        self.llm.plans.append({"steps": [], "direct_response": "?"})
        orchestrator.query("evet", thread_id="t1", user=self.user)
        self.assertEqual(len(self.store.list()), 1)

    def test_a_request_about_the_earlier_answer_gets_its_subject_from_the_conversation(self):
        orchestrator = self.orchestrator([{"steps": [step("doc_agent", "q")]}, {"steps": [step("request_agent", "x")]}])
        orchestrator.query("Yaz okulunda kaç ders alabilirim?", thread_id="t6", user=self.user)
        orchestrator.query("Bu cevap yetersizdi, bununla ilgili talep oluştur", thread_id="t6", user=self.user)
        extractor_input = self.llm.request_inputs[-1]
        self.assertIn("Yaz okulunda kaç ders alabilirim?", extractor_input)
        self.assertTrue(extractor_input.endswith("Bu cevap yetersizdi, bununla ilgili talep oluştur"))

    def test_no_discards_the_draft(self):
        orchestrator = self.orchestrator([{"steps": [step("request_agent", "x")]}])
        orchestrator.query("Arıza kaydı aç: yazıcı çalışmıyor", thread_id="t2", user=self.user)
        result = orchestrator.query("hayır", thread_id="t2", user=self.user)
        self.assertIn("oluşturulmadı", result["answer"])
        self.llm.plans.append({"steps": [], "direct_response": "?"})
        orchestrator.query("evet", thread_id="t2", user=self.user)
        self.assertEqual(self.store.list(), [])

    def test_another_question_discards_the_draft(self):
        orchestrator = self.orchestrator([{"steps": [step("request_agent", "x")]}, {"steps": [step("doc_agent", "q")]}])
        orchestrator.query("Arıza kaydı aç: klima bozuk", thread_id="t3", user=self.user)
        orchestrator.query("Yıllık izin kaç gün?", thread_id="t3", user=self.user)
        self.llm.plans.append({"steps": [], "direct_response": "?"})
        orchestrator.query("evet", thread_id="t3", user=self.user)
        self.assertEqual(self.store.list(), [])

    def test_without_a_session_the_request_is_filed_directly(self):
        result = self.orchestrator([{"steps": [step("request_agent", "x")]}]).query("Arıza kaydı aç", user=self.user)
        self.assertEqual(len(self.store.list()), 1)
        self.assertIn("#1", result["answer"])

    def test_requests_need_a_logged_in_user(self):
        result = self.orchestrator([{"steps": [step("request_agent", "x")]}]).query("Arıza kaydı aç", thread_id="t4")
        self.assertIn("giriş", result["answer"])
        self.assertEqual(self.store.list(), [])

    def test_lists_only_the_users_own_requests(self):
        self.store.create("ayse", "it_support", "Benim talebim")
        self.store.create("mehmet", "facilities", "Başkasının talebi")
        orchestrator = self.orchestrator([{"steps": [step("request_agent", "x")]}])
        self.llm.request = {"action": "list"}
        result = orchestrator.query("Taleplerimin durumu nedir?", thread_id="t5", user=self.user)
        self.assertIn("Benim talebim", result["answer"])
        self.assertNotIn("Başkasının", result["answer"])


if __name__ == "__main__":
    unittest.main()
