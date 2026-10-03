"""Behavior of the built-in specialists: doc_agent's Self-RAG guard, db_agent, and supervisor routing."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.grading import (
    grade_from_quotes,
    grade_objection,
    is_grade_passed,
    numbers_grounded,
    quote_in_context,
)
from src.agent.prompts import (
    FALLBACK_RESPONSE,
    SYSTEM_PROMPT_GRADER,
    SYSTEM_PROMPT_GRADER_QUOTES,
    SYSTEM_PROMPT_REFINE,
)


def scripted_chat_model(generate: str, grades: list, refined: str = "refined answer") -> MagicMock:
    """Chat model that answers by prompt type: grader -> next grade, refine -> refined, otherwise generate."""
    grade_iter = iter(grades)

    def invoke(messages):
        system = messages[0].content
        # startswith: agents append a response-language instruction to some system prompts
        if system.startswith((SYSTEM_PROMPT_GRADER, SYSTEM_PROMPT_GRADER_QUOTES)):
            return MagicMock(content=next(grade_iter))
        if system.startswith(SYSTEM_PROMPT_REFINE):
            return MagicMock(content=refined)
        return MagicMock(content=generate)

    chat = MagicMock()
    chat.invoke.side_effect = invoke
    return chat


class TestDocAgentSelfRag(unittest.TestCase):
    """Grade -> refine -> fallback with scripted grades; the second opinion is tested in test_verification.py."""

    def setUp(self):
        # The scripted grades below are in the quotes format without "answers_question";
        # test_the_default_grader_points_to_sentences covers the defaults
        for setting, value in (
            ("GRADER_SECOND_OPINION", False),
            ("GRADER_MODE", "quotes"),
            ("GRADER_RELEVANCE_CHECK", False),
        ):
            patcher = patch(f"src.core.config.{setting}", value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _agent(self, chat):
        engine = MagicMock()
        engine.search.return_value = {
            "context": "Annual leave is 20 days.",
            "sources": [{"source": "hr.txt"}],
        }
        return DocumentRagAgent(chat_model=chat, rag_engine=engine)

    def test_grounded_answer_passes(self):
        out = self._agent(scripted_chat_model("20 days.", ["yes"])).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")
        self.assertFalse(out["is_refined"])
        self.assertEqual(out["hallucination_grade"], "yes")

    def test_ungrounded_answer_is_refined(self):
        chat = scripted_chat_model("20 days and free cars.", ["no", "yes"], refined="20 days.")
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")
        self.assertTrue(out["is_refined"])

    def test_unverifiable_answer_falls_back(self):
        chat = scripted_chat_model("Made up.", ["no", "no"], refined="Still made up.")
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], FALLBACK_RESPONSE)

    def test_grader_failure_fails_closed(self):
        chat = MagicMock()
        # Generation and refinement work; every grading attempt (JSON mode and the plain retry) fails
        replies = iter([MagicMock(content="Answer"), MagicMock(content="Answer")])

        def invoke(messages):
            if messages[0].content.startswith((SYSTEM_PROMPT_GRADER, SYSTEM_PROMPT_GRADER_QUOTES)):
                raise RuntimeError("down")
            return next(replies)

        chat.invoke.side_effect = invoke
        out = self._agent(chat).execute({"question": "Q?"})
        self.assertEqual(out["final_answer"], FALLBACK_RESPONSE)

    def test_refinement_is_told_the_graders_objection(self):
        grades = iter(
            [
                '{"supported": "no", "problem": "free cars", "quotes": []}',
                '{"supported": "yes", "problem": "", "quotes": []}',
            ]
        )
        refine_prompts = []

        def invoke(messages):
            system = messages[0].content
            if system.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
                return MagicMock(content=next(grades))
            if system.startswith(SYSTEM_PROMPT_REFINE):
                refine_prompts.append(messages[1].content)
                return MagicMock(content="20 days.")
            return MagicMock(content="20 days and free cars.")

        chat = MagicMock()
        chat.invoke.side_effect = invoke
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")
        self.assertTrue(refine_prompts[0].endswith("Auditor's objection: free cars"))
        self.assertEqual(grade_objection("no (grader unavailable)"), "")

    def test_grader_is_retried_without_json_mode(self):
        attempts = []

        def invoke(messages):
            if messages[0].content.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
                attempts.append(1)
                if len(attempts) == 1:
                    raise RuntimeError("prediction aborted, token repeat limit reached")
                return MagicMock(content='{"supported": "yes", "problem": "", "quotes": []}')
            return MagicMock(content="20 days.")

        chat = MagicMock()
        chat.invoke.side_effect = invoke
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual((out["final_answer"], out["hallucination_grade"]), ("20 days.", "yes"))

    def test_an_answer_that_slips_into_another_script_is_written_again(self):
        chat = MagicMock()
        replies = iter(["20 days. 条件下不符合规则", "20 days."])

        def invoke(messages):
            if messages[0].content.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
                return MagicMock(content="yes")
            return MagicMock(content=next(replies))

        chat.invoke.side_effect = invoke
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], "20 days.")

    def test_the_default_grader_points_to_sentences(self):
        grader_prompts = []

        def invoke(messages):
            if messages[0].content.startswith("You are a factual auditor"):
                grader_prompts.append(messages[1].content)
                return MagicMock(
                    content='{"supported": "yes", "problem": "", "answers_question": "yes", "sentences": [1]}'
                )
            return MagicMock(content="20 days.")

        chat = MagicMock()
        chat.invoke.side_effect = invoke
        with patch("src.core.config.GRADER_MODE", "sentences"), patch("src.core.config.GRADER_RELEVANCE_CHECK", True):
            out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual((out["final_answer"], out["verification"]["level"]), ("20 days.", "verified"))
        self.assertIn("[1] Annual leave is 20 days.", grader_prompts[0])

    def test_grade_parsing(self):
        self.assertTrue(is_grade_passed("yes"))
        self.assertTrue(is_grade_passed("Evet, belgelerle tutarlı"))
        self.assertFalse(is_grade_passed("no, not yes"))
        self.assertFalse(is_grade_passed(""))

    def test_quote_grader_rejects_invented_quotes(self):
        grade = '{"supported": "yes", "problem": "", "quotes": ["Annual leave is 30 days for everyone."]}'
        chat = scripted_chat_model("30 days.", [grade, grade], refined="30 days.")
        out = self._agent(chat).execute({"question": "How many leave days?"})
        self.assertEqual(out["final_answer"], FALLBACK_RESPONSE)
        self.assertIn("quote not found", out["hallucination_grade"])


class TestQuoteGrading(unittest.TestCase):
    CONTEXT = "[YÖNETMELİK | Madde 12 – Devam]\nÖğrenciler teorik derslerin en az %70'ine devam etmek zorundadır."

    def _grade(self, quotes, supported="yes", problem=""):
        reply = json.dumps({"supported": supported, "problem": problem, "quotes": quotes})
        return grade_from_quotes(reply, self.CONTEXT)

    def test_quotes_from_the_context_pass(self):
        # Small differences in copying (a dropped word, İ/i) are tolerated; empty quotes are ignored
        self.assertEqual(self._grade(["öğrenciler teorik derslerin en az %70'ine devam etmek ZORUNDADIR", ""]), "yes")

    def test_invented_quote_fails(self):
        grade = self._grade(["Uygulamalı derslerin %80'ine devam zorunludur."])
        self.assertTrue(grade.startswith("no: quote not found"))

    def test_grader_verdict_no_is_kept(self):
        grade = self._grade([], supported="no", problem="%80 is not in the context")
        self.assertEqual(grade, "no: %80 is not in the context")

    def test_reply_cut_off_by_the_token_limit_keeps_its_verdict(self):
        reply = '{"supported": "yes", "problem": "", "quotes": ["teorik derslerin en az %70\'ine devam", "Öğrenciler te'
        self.assertEqual(grade_from_quotes(reply, self.CONTEXT), "yes")
        reply = '{"supported": "yes", "problem": "", "quotes": ["derslerin %80 oranında devamı gerekir", "Öğr'
        self.assertFalse(is_grade_passed(grade_from_quotes(reply, self.CONTEXT)))

    def test_objection_stated_in_the_context_is_a_grader_mistake(self):
        answer = "Öğrenciler teorik derslerin en az %70'ine devam etmek zorundadır (Madde 12)."
        reply = json.dumps({"supported": "no", "problem": "en az %70'ine devam", "quotes": []})
        grade = grade_from_quotes(reply, self.CONTEXT, answer=answer, question="Devam zorunluluğu nedir?")
        self.assertTrue(is_grade_passed(grade), grade)

    def test_objection_override_still_requires_grounded_numbers(self):
        # The objection is in the context, but the answer's 80 is not: stays rejected
        answer = "Öğrenciler derslerin en az %80'ine devam etmek zorundadır."
        reply = json.dumps({"supported": "no", "problem": "en az %70'ine devam", "quotes": []})
        self.assertFalse(is_grade_passed(grade_from_quotes(reply, self.CONTEXT, answer=answer)))
        # A one-word objection or one not in the context is kept
        for problem in ("devam", "%80 devam şartı"):
            reply = json.dumps({"supported": "no", "problem": problem, "quotes": []})
            self.assertFalse(is_grade_passed(grade_from_quotes(reply, self.CONTEXT, answer="%70.")))

    def test_numbers_grounded(self):
        self.assertTrue(numbers_grounded("AGNO en az 2,0 olmalıdır.", "başarı notu 2,00’dır"))
        self.assertTrue(
            numbers_grounded("2020 yılından en az 5 yıl sonra", "en az beş (5) yıl", question="2020 yılında")
        )
        # Computed numbers are not in the documents: such answers keep a "no" of the grader
        self.assertFalse(numbers_grounded("2025 yılında", "en az beş (5) yıl", question="2020 yılında"))
        self.assertFalse(numbers_grounded("en az 65 puan", "en az elli beş (55) puan"))

    def test_plain_text_reply_falls_back_to_yes_no(self):
        self.assertEqual(grade_from_quotes("yes", self.CONTEXT), "yes")
        self.assertFalse(is_grade_passed(grade_from_quotes("", self.CONTEXT)))
        self.assertTrue(quote_in_context("İzin", "izin"))


class TestDbAgent(unittest.TestCase):
    def _connector(self, query_result):
        connector = MagicMock()
        connector.is_connected = True
        connector.dialect = "sqlite"
        connector.get_schema_summary.return_value = "Table: urunler"
        connector.execute_query.return_value = query_result
        return connector

    def test_guard_error_stays_in_the_trace(self):
        connector = self._connector(
            {
                "status": "error",
                "message": "Security Guard: nope",
                "columns": [],
                "rows": [],
            }
        )
        chat = MagicMock()
        chat.invoke.return_value = MagicMock(content="SELECT * FROM secret")
        out = DatabaseAgent(chat_model=chat, db_connector=connector).execute({"question": "q"})
        # Database errors can reveal schema details: users get a generic message, the trace keeps the cause
        self.assertNotIn("Security Guard: nope", out["final_answer"])
        self.assertEqual(out["agent_trace"][-1]["error"], "Security Guard: nope")
        self.assertEqual(out["agent_trace"][-1]["status"], "rejected")

    def test_row_count_and_first_statement(self):
        rows = [{"id": 1}, {"id": 2}]
        connector = self._connector({"status": "success", "columns": ["id"], "rows": rows, "row_count": 2})
        chat = MagicMock()
        chat.invoke.side_effect = [
            MagicMock(content="```sql\nSELECT id FROM t WHERE name = 'a;b'; DROP TABLE t\n```"),
            MagicMock(content="Two rows."),
        ]
        out = DatabaseAgent(chat_model=chat, db_connector=connector).execute({"question": "q"})
        connector.execute_query.assert_called_once_with("SELECT id FROM t WHERE name = 'a;b'")
        self.assertEqual(out["agent_trace"][-1]["row_count"], 2)
        explain_prompt = chat.invoke.call_args_list[1][0][0][1].content
        self.assertIn("Row Count: 2", explain_prompt)

    def test_generation_error_does_not_leak(self):
        chat = MagicMock()
        chat.invoke.side_effect = RuntimeError("internal host 10.0.0.5")
        out = DatabaseAgent(chat_model=chat, db_connector=self._connector({})).execute({"question": "q"})
        self.assertNotIn("10.0.0.5", out["final_answer"])


class TestSupervisorRouting(unittest.TestCase):
    def setUp(self):
        self.chat = MagicMock()
        self.chat.invoke.return_value = MagicMock(content='{"agent": "finish", "reason": "r", "direct_response": "ok"}')
        self.supervisor = SupervisorAgent(chat_model=self.chat, registry=AgentRegistry())

    def test_pure_greeting_short_circuits(self):
        for greeting in ("Hello", "Merhaba, nasılsın?", "hi there", "iyi günler"):
            out = self.supervisor.route({"question": greeting})
            self.assertEqual(out["agent_trace"][-1]["action"], "direct_greeting", greeting)
        self.chat.invoke.assert_not_called()

    def test_thanks_and_goodbyes_short_circuit(self):
        for thanks in ("Teşekkürler", "çok teşekkür ederim", "Sağ olun!", "tamam teşekkürler", "Thank you very much"):
            out = self.supervisor.route({"question": thanks})
            self.assertEqual(out["agent_trace"][-1]["action"], "direct_thanks", thanks)
            self.assertTrue(out["final_answer"].startswith(("Rica ederim", "You're welcome")), thanks)
        self.chat.invoke.assert_not_called()

    def test_thanks_with_a_question_is_routed(self):
        for question in ("teşekkürler, yıllık izin kaç gün?", "çok"):
            out = self.supervisor.route({"question": question})
            self.assertEqual(out["agent_trace"][-1]["action"], "intent_routing", question)

    def test_greeting_and_thanks_tell_users_who_can_file_requests_how(self):
        self.supervisor.registry.is_available = lambda name: name == "request_agent"
        viewer = {"username": "ayse", "role": "viewer"}
        for question in ("Merhaba", "Teşekkürler"):
            answer = self.supervisor.route({"question": question, "user": viewer})["final_answer"]
            self.assertIn("Talep oluştur:", answer, question)
            # Not for guests, who cannot file requests, nor without a logged-in user
            guest = {"username": "guest-1", "role": "guest"}
            self.assertNotIn(
                "Talep oluştur:", self.supervisor.route({"question": question, "user": guest})["final_answer"]
            )
            self.assertNotIn("Talep oluştur:", self.supervisor.route({"question": question})["final_answer"])
        # Nor when the request agent is not running
        self.supervisor.registry.is_available = lambda name: False
        self.assertNotIn(
            "Talep oluştur:", self.supervisor.route({"question": "Merhaba", "user": viewer})["final_answer"]
        )

    def test_greeting_with_request_is_routed(self):
        out = self.supervisor.route({"question": "hi, list sales"})
        self.assertEqual(out["agent_trace"][-1]["action"], "intent_routing")
        self.chat.invoke.assert_called_once()

    def test_routing_prompt_includes_history(self):
        history = [{"question": "Top product by sales?", "answer": "X", "agent": "db_agent"}]
        self.supervisor.route({"question": "And last month?", "chat_history": history})
        human = self.chat.invoke.call_args[0][0][1].content
        self.assertIn("Top product by sales?", human)
        self.assertIn("db_agent", human)
