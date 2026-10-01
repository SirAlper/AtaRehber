"""Clarifying questions, steps that build on earlier steps, step timeouts, and the user's profile."""

import time
import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.agent.answer_cache import answer_cache
from src.agent.language import message, message_variants
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent, needs_rewrite
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.auth.profile import normalize_profile, profile_note
from tests.agents.test_agent_collaboration import ScriptedLLM, StubAgent, build, step

CLARIFY = {"steps": [], "clarify": {"question": "Hangi izin türünü soruyorsunuz?", "options": ["Yıllık", "Mazeret"]}}
STUDENT = {
    "username": "ogr",
    "role": "viewer",
    "groups": [],
    "profile": {"unit": "Mühendislik Fakültesi", "program": "Bilgisayar Mühendisliği", "level": "3. sınıf"},
}


class RecordingAgent(StubAgent):
    """Stub agent that keeps the state of each call (question, earlier answers)."""

    def __init__(self, name, answer=None, delay=0.0):
        super().__init__(name, answer=answer)
        self.states = []
        self.delay = delay

    def execute(self, state):
        self.states.append(state)
        if self.delay:
            time.sleep(self.delay)
        return super().execute(state)


class TestClarifyingQuestions(unittest.TestCase):
    def test_an_ambiguous_question_is_asked_back_and_the_answer_completes_it(self):
        doc = RecordingAgent("doc_agent", answer="Yıllık izin 14 gündür.")
        llm = ScriptedLLM(plans=[CLARIFY, {"steps": [step("doc_agent", "Yıllık izin süresi ne kadar?")]}])
        orchestrator = build(llm, doc)

        first = orchestrator.query("İzin süresi ne kadar?", thread_id="c1")
        self.assertEqual(first["clarification"], CLARIFY["clarify"])
        self.assertEqual(first["answer"], "Hangi izin türünü soruyorsunuz?\n\n- Yıllık\n- Mazeret")
        self.assertEqual(doc.states, [])

        second = orchestrator.query("Yıllık", thread_id="c1")
        self.assertIsNone(second["clarification"])
        self.assertEqual(second["answer"], "Yıllık izin 14 gündür.")
        # The supervisor saw the original question together with the answer
        self.assertEqual(llm.routing_inputs[-1].rsplit("Current question: ", 1)[-1], "İzin süresi ne kadar? (Yıllık)")

    def test_never_twice_in_a_row_and_never_without_a_conversation(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=AgentRegistry())
        supervisor.registry.is_available = lambda name: name == "doc_agent"
        supervisor.chat_model.invoke.return_value = MagicMock(
            content='{"steps": [], "clarify": {"question": "Hangisi?"}}'
        )
        # Stateless API call: nobody could answer the question back
        self.assertNotIn("clarification", supervisor.route({"question": "İzin ne kadar?"}))
        # Right after a question back the answer is routed, not asked about again
        pending = {"question": "İzin ne kadar?"}
        decision = supervisor.route(
            {"question": "Hangisi olursa", "has_session": True, "pending_clarification": pending}
        )
        self.assertNotIn("clarification", decision)
        self.assertIsNone(decision["pending_clarification"])

    def test_the_clarify_rule_is_offered_only_in_conversations(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=AgentRegistry())
        supervisor.chat_model.invoke.return_value = MagicMock(content='{"steps": [], "direct_response": "?"}')
        supervisor.route({"question": "İzin ne kadar?"})
        self.assertNotIn("CLARIFYING QUESTIONS", supervisor.chat_model.invoke.call_args[0][0][0].content)
        supervisor.route({"question": "İzin ne kadar?", "has_session": True})
        self.assertIn("CLARIFYING QUESTIONS", supervisor.chat_model.invoke.call_args[0][0][0].content)


LEAVE = "(1) Kıdemi 1-5 yıl olanlara 14 gün, 5-15 yıl olanlara 20 gün yıllık izin verilir."


def asks_back(reply, question="Kaç gün izin hakkım var?", **state):
    """What doc_agent does with the clarifier's reply: (its question back or None, whether the clarifier ran)."""
    model = MagicMock()
    model.invoke.side_effect = [AIMessage(content=reply), AIMessage(content="14 veya 20 gün.")] + [
        AIMessage(content='{"supported": "yes", "problem": "", "quotes": ["14 gün"]}')
    ] * 4
    state = {"question": question, "has_session": True, "plan": [{"agent": "doc_agent"}], **state}
    out = DocumentRagAgent(chat_model=model, rag_engine=engine(LEAVE)).execute(state)
    asked_model = any("depends_on" in call[0][0][0].content for call in model.invoke.call_args_list)
    return out.get("clarification"), asked_model


class TestDocAgentAsksBack(unittest.TestCase):
    ASK = (
        '{"depends_on": "kıdem", "stated": false, "question": "Kıdeminiz kaç yıl?", "options": ["1-5 yıl", "5-15 yıl"]}'
    )

    def setUp(self):
        answer_cache.clear()

    def test_it_asks_when_the_rules_depend_on_something_the_user_did_not_say(self):
        clarification, _ = asks_back(self.ASK)
        self.assertEqual(clarification, {"question": "Kıdeminiz kaç yıl?", "options": ["1-5 yıl", "5-15 yıl"]})

    def test_it_answers_when_the_case_is_stated_or_there_is_only_one(self):
        self.assertIsNone(asks_back(self.ASK.replace('"stated": false', '"stated": true'))[0])
        self.assertIsNone(asks_back(self.ASK.replace('"kıdem"', '""'))[0])

    def test_badly_formed_questions_back_are_not_shown(self):
        same = self.ASK.replace("Kıdeminiz kaç yıl?", "Kaç gün izin hakkım var?")
        self.assertIsNone(asks_back(same)[0])
        long = self.ASK.replace('"1-5 yıl"', '"Kıdemi bir ile beş yıl arasında olan çalışanlar"')
        self.assertIsNone(asks_back(long)[0])

    def test_no_model_call_for_general_questions_after_a_question_back_or_outside_a_conversation(self):
        # "Yıllık izin kaç gün?" is not about the asker: the answer lists the cases
        self.assertEqual(asks_back(self.ASK, question="Yıllık izin kaç gündür?"), (None, False))
        self.assertIsNone(asks_back(self.ASK, clarified=True)[0])
        self.assertIsNone(asks_back(self.ASK, has_session=False)[0])
        self.assertIsNone(asks_back(self.ASK, plan=[{"agent": "doc_agent"}, {"agent": "db_agent"}])[0])

    def test_a_guest_answer_to_a_question_back_completes_the_original_question(self):
        doc = RecordingAgent("doc_agent", answer="20 gün.")
        orchestrator = build(ScriptedLLM(), doc)
        pending = {"question": "Kaç gün izin hakkım var?"}
        orchestrator.app.update_state({"configurable": {"thread_id": "g1"}}, {"pending_clarification": pending})
        orchestrator.query("5-15 yıl", thread_id="g1", forced_agent="doc_agent", user={"role": "guest"})
        self.assertEqual(doc.states[0]["question"], "Kaç gün izin hakkım var? (5-15 yıl)")
        self.assertTrue(doc.states[0]["clarified"])


class TestStepsThatBuildOnEarlierSteps(unittest.TestCase):
    def test_a_step_gets_the_answers_it_uses_and_the_combined_answer_may_conclude(self):
        db = RecordingAgent("db_agent", answer="En az stoklu ürün: Kablo (2 adet).")
        doc = RecordingAgent("doc_agent", answer="Kablolar 14 gün içinde iade edilebilir.")
        plan = {
            "steps": [
                step("db_agent", "Stoğu en az olan ürün hangisi?"),
                {**step("doc_agent", "Bu ürünün iade süresi nedir?"), "uses": [0]},
            ]
        }
        llm = ScriptedLLM(plans=[plan], synthesis="Kablo; 14 gün içinde iade edilebilir.")
        result = build(llm, db, doc).query("En az stoklu ürün ve iade süresi?")
        self.assertEqual(db.states[0]["step_context"], [])
        self.assertEqual(
            doc.states[0]["step_context"],
            [
                {
                    "agent": "DB_AGENT",
                    "question": "Stoğu en az olan ürün hangisi?",
                    "answer": "En az stoklu ürün: Kablo (2 adet).",
                }
            ],
        )
        self.assertEqual(result["answer"], "Kablo; 14 gün içinde iade edilebilir.")
        # The combined answer is checked with the rule that conclusions drawn from the parts are supported
        self.assertIn("conclusion drawn from them", llm.grader_inputs[-1])

    def test_uses_point_to_kept_steps_only(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=AgentRegistry())
        supervisor.registry.is_available = lambda name: name in ("doc_agent", "db_agent")
        raw = [
            {"agent": "db_agent", "question": "a"},
            {"agent": "db_agent", "question": "duplicate, dropped"},
            {"agent": "doc_agent", "question": "c", "uses": [1, 0, 5, True]},
        ]
        plan = supervisor._validate_plan(raw, "q")
        self.assertEqual(plan[1], {"agent": "doc_agent", "question": "c", "id": 1, "uses": [0]})


class TestStepTimeout(unittest.TestCase):
    def test_a_slow_step_gives_up_and_the_other_steps_still_count(self):
        slow = RecordingAgent("db_agent", answer="late", delay=1.5)
        doc = RecordingAgent("doc_agent", answer="Kural: 14 gün.")
        plan = {"steps": [step("db_agent", "x"), step("doc_agent", "y")]}
        llm = ScriptedLLM(plans=[plan], synthesis="COMBINED")
        with patch("src.agent.multi_agent.orchestrator_graph.AGENT_STEP_TIMEOUT_SECONDS", 0.3):
            started = time.time()
            result = build(llm, slow, doc).query("x ve y?")
        self.assertLess(time.time() - started, 1.4)
        timeout = [e for e in result["agent_trace"] if e.get("action") == "timeout"]
        self.assertEqual(timeout[0]["agent"], "db_agent")
        self.assertEqual(len(doc.states), 1)
        # A question without language cues ("x") gets the default language
        self.assertTrue(any(text in llm.synthesis_inputs[-1] for text in message_variants("step_timeout")))


def engine(context="(1) Mühendislik Fakültesinde devam zorunluluğu yüzde 70'tir.", sources=None):
    rag = MagicMock()
    rag.index_version = 0
    rag.search.return_value = {
        "context": context,
        "sources": sources if sources is not None else [{"source": "y.txt", "chunk_index": 0, "content": context}],
    }
    return rag


class TestProfile(unittest.TestCase):
    def setUp(self):
        answer_cache.clear()

    def test_profiles_are_cleaned_and_described_for_the_prompt(self):
        self.assertEqual(normalize_profile({"unit": "  Fen  Fakültesi ", "level": ""}), {"unit": "Fen Fakültesi"})
        with self.assertRaises(ValueError):
            normalize_profile({"faculty": "x"})
        note = profile_note(STUDENT)
        self.assertIn("unit: Mühendislik Fakültesi; program: Bilgisayar Mühendisliği; level: 3. sınıf", note)
        self.assertEqual(profile_note({"username": "x"}), "")

    def test_questions_about_my_department_are_searched_for_the_users_department(self):
        self.assertTrue(needs_rewrite("Bölümümde devam zorunluluğu var mı?", [], has_profile=True))
        self.assertFalse(needs_rewrite("Bölümümde devam zorunluluğu var mı?", [], has_profile=False))
        self.assertFalse(needs_rewrite("Devam zorunluluğu yüzde kaç?", [], has_profile=True))

        model = MagicMock()
        model.invoke.side_effect = [
            AIMessage(content="Mühendislik Fakültesi devam zorunluluğu"),
            AIMessage(content="Yüzde 70."),
            AIMessage(content='{"supported": "yes", "problem": "", "quotes": ["yüzde 70"]}'),
        ]
        rag = engine()
        DocumentRagAgent(chat_model=model, rag_engine=rag).execute(
            {"question": "Bölümümde devam zorunluluğu yüzde kaç?", "user": STUDENT}
        )
        self.assertEqual(rag.search.call_args[0][0], "Mühendislik Fakültesi devam zorunluluğu")
        rewrite_prompt, answer_prompt = model.invoke.call_args_list[0][0][0], model.invoke.call_args_list[1][0][0]
        self.assertIn("Mühendislik Fakültesi", rewrite_prompt[0].content)
        self.assertIn("level: 3. sınıf", answer_prompt[0].content)

    def test_cached_answers_are_kept_apart_per_profile(self):
        key = answer_cache.key("Soru?", None, 0, profile_note(STUDENT))
        self.assertNotEqual(key, answer_cache.key("Soru?", None, 0, ""))


class TestUnansweredQuestions(unittest.TestCase):
    def test_not_found_answers_are_marked_for_review(self):
        out = DocumentRagAgent(chat_model=MagicMock(), rag_engine=engine(context="", sources=[])).execute(
            {"question": "Yemekhane kaçta açılır?"}
        )
        self.assertEqual(out["final_answer"], message("no_context", "tr"))
        self.assertEqual(out["verification"], {"level": "unverified", "issues": ["not_found"]})


if __name__ == "__main__":
    unittest.main()
