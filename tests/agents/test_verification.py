"""Answer check: second opinion, number and transitional-article checks, partial answers, levels, review list."""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.agent.language import message
from src.agent.multi_agent.orchestrator_graph import _combined_verification
from src.agent.grading import cited_sentences, grade_from_quotes, grade_from_sentences, number_sentences
from src.agent.language import foreign_script
from src.agent.self_rag import refine_answer
from src.agent.verification import (
    PARTIAL,
    UNVERIFIED,
    VERIFIED,
    check_answer,
    partial_answer,
    relies_only_on_transitional,
    unsupported_numbers,
    verify_answer,
)
from src.api import main as api_main
from src.api.main import app
from src.auth.jwt_handler import create_access_token

CONTEXT = "[KANUN | Madde 54]\n(10) Disiplin cezalarına karşı on beş gün içinde itiraz edilir."
QUOTE = "Disiplin cezalarına karşı on beş gün içinde itiraz edilir"
SOURCES = [{"source": "kanun.txt", "chunk_index": 1, "article": "Madde 54 – Disiplin", "content": CONTEXT}]


def grade(supported="yes", problem="", quotes=(QUOTE,)):
    # Both evidence formats: the copied quotes (GRADER_MODE=quotes) and the number of the context's first
    # sentence, which the quotes of these tests come from (GRADER_MODE=sentences, the default)
    verdict = {"supported": supported, "problem": problem, "quotes": list(quotes)}
    verdict["sentences"] = [1] if quotes else []
    return json.dumps(verdict, ensure_ascii=False)


class Grader:
    """Scripted grader and editor: grader prompts get the next grade, the editor the next refined answer."""

    def __init__(self, grades, refined=()):
        self.grades, self.refined, self.prompts, self.contexts = list(grades), list(refined), [], []

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        if messages[0].content.startswith("You are a factual auditor"):
            self.contexts.append(messages[1].content)
            return AIMessage(content=self.grades.pop(0))
        # The editor's prompt is localized, so everything else is the refinement
        return AIMessage(content=self.refined.pop(0))


class TestCodeChecks(unittest.TestCase):
    def test_every_number_must_be_in_the_quotes_question_or_tool_results(self):
        self.assertEqual(unsupported_numbers("İtiraz süresi 15 gündür (Madde 54/10).", [QUOTE], "", ""), [])
        self.assertEqual(unsupported_numbers("İtiraz süresi 30 gündür.", [QUOTE], "", ""), ["30"])
        # Article, paragraph, and item references and amendment notes are no facts
        for reference in (
            "Madde 17(2) ve Madde 32, 1 uyarınca 15 gün.",
            "(1) ve (3) numaralı fıkralara, a) 1) ve 2) bentlerine göre 15 gün.",
            "Madde 25 – (Değişik:RG-14/4/2024-32517) 15 gün.",
        ):
            self.assertEqual(unsupported_numbers(reference, [QUOTE], "", ""), [], reference)
        # References are no facts; numbers from the question and computed values are allowed
        self.assertEqual(unsupported_numbers("2547 sayılı Kanunun 54 üncü maddesine göre 15 gün.", [QUOTE], "", ""), [])
        self.assertEqual(
            unsupported_numbers("Son gün 2026-10-16.", [QUOTE], "1 Ekim 2026", "[dates] 2026-10-01 + 15 = 2026-10-16"),
            [],
        )

    def test_transitional_only_evidence_is_detected(self):
        in_force = {"article": "Madde 24 – Doçentlik", "content": "en az elli beş (55) puan"}
        transitional = {"article": "Geçici Madde 47", "content": "65 puan", "used": True}
        self.assertEqual(relies_only_on_transitional([transitional, in_force], "Kaç puan gerekir?"), "Geçici Madde 47")
        self.assertIsNone(relies_only_on_transitional([transitional, in_force], "Geçici maddeye göre kaç puan?"))
        self.assertIsNone(relies_only_on_transitional([transitional], "Kaç puan gerekir?"))
        self.assertIsNone(relies_only_on_transitional([{**in_force, "used": True}, transitional], "Kaç puan?"))

    def test_partial_answers_keep_only_supported_sentences(self):
        answer = "İtiraz süresi on beş gündür. Ayrıca rektör bu süreyi 45 güne uzatabilir."
        self.assertEqual(partial_answer(answer, [QUOTE], "", ""), "İtiraz süresi on beş gündür.")
        self.assertEqual(partial_answer("İtiraz süresi on beş gündür.", [QUOTE], "", ""), "", "nothing to drop")
        self.assertEqual(partial_answer("Rektör 45 gün verir.", [QUOTE], "", ""), "", "nothing supported")


class TestCheckAnswer(unittest.TestCase):
    def check(self, answer, grades, sources=SOURCES, question="İtiraz süresi kaç gün?", strict=True):
        return check_answer(Grader(grades), CONTEXT, question, answer, sources, strict=strict)

    def test_a_second_opinion_can_overturn_a_rejection(self):
        result = self.check("İtiraz süresi 15 gündür.", [grade("no", "süre belirtilmemiş", ()), grade()])
        self.assertTrue(result.passed)
        self.assertFalse(result.first_verdict)
        with patch("src.core.config.GRADER_SECOND_OPINION", False):
            self.assertFalse(self.check("İtiraz süresi 15 gündür.", [grade("no", "x", ())]).passed)

    def test_the_second_opinion_sees_the_objection(self):
        grader = Grader([grade("no", "on beş gün yazmıyor", ()), grade("no", "yine yok", ())])
        check_answer(grader, CONTEXT, "Süre?", "15 gün.", SOURCES)
        self.assertIn("on beş gün yazmıyor", grader.prompts[1])

    def test_a_wrong_number_fails_even_if_the_grader_accepts(self):
        result = self.check("İtiraz süresi 30 gündür.", [grade()])
        self.assertFalse(result.passed)
        self.assertTrue(result.first_verdict)
        self.assertIn("30", result.objection)

    def test_numbers_next_to_the_quoted_sentence_count(self):
        # The grader quoted the rule but not the numbers after it; they are in the same article
        context = "[YÖNETMELİK | Madde 40]\n(1) Onur öğrencisi: AGNO'su 3,00 - 3,49 olan öğrenciler."
        sources = [{"source": "y", "chunk_index": 1, "article": "Madde 40", "content": context}]
        result = check_answer(
            Grader([grade(quotes=["Onur öğrencisi"])]), context, "Aralık?", "AGNO 3,00-3,49 olmalıdır.", sources
        )
        self.assertTrue(result.passed, result.grade)

    def test_transitional_evidence_is_sent_back_once(self):
        sources = [
            {"article": "Geçici Madde 47", "content": CONTEXT, "chunk_index": 1, "source": "k"},
            {"article": "Madde 24 – Doçentlik", "content": "başka metin", "chunk_index": 2, "source": "k"},
        ]
        strict = self.check("15 gün.", [grade()], sources=sources)
        self.assertFalse(strict.passed)
        self.assertIn("Geçici Madde 47", strict.objection)
        lenient = self.check("15 gün.", [grade()], sources=sources, strict=False)
        self.assertTrue(lenient.passed)
        self.assertEqual(lenient.warnings, ["transitional"])


class TestEvidenceBySentenceNumber(unittest.TestCase):
    """GRADER_MODE=sentences: the grader points to numbered sentences instead of copying them."""

    CONTEXT = (
        "[KANUN | Madde 54]\n(10) Disiplin cezalarına karşı on beş gün içinde itiraz edilir. İtiraz kurula yapılır.\n\n"
        "[KANUN | Madde 55]\nSoruşturma iki ay içinde bitirilir."
    )

    def test_sentences_are_numbered_and_headers_are_not(self):
        numbered, sentences = number_sentences(self.CONTEXT)
        self.assertEqual(len(sentences), 3)
        self.assertIn(
            "[KANUN | Madde 54]\n[1] (10) Disiplin cezalarına karşı on beş gün içinde itiraz edilir.", numbered
        )
        self.assertIn("\n[2] İtiraz kurula yapılır.\n\n[KANUN | Madde 55]\n[3] Soruşturma", numbered)

    def test_cited_numbers_become_the_evidence(self):
        sentences = number_sentences(self.CONTEXT)[1]
        reply = '{"supported": "yes", "sentences": [3, 1, 3, 9]}'
        self.assertEqual(cited_sentences(reply, sentences), [sentences[2], sentences[0]])
        # Numbers as text, and a reply cut off by the token limit
        self.assertEqual(cited_sentences('{"supported": "yes", "sentences": ["[2]", "1', sentences), sentences[1::-1])
        self.assertEqual(cited_sentences('{"supported": "yes"}', sentences), [])
        self.assertEqual(grade_from_sentences('{"supported": "yes", "sentences": [1]}', self.CONTEXT), "yes")
        self.assertEqual(grade_from_sentences('{"supported": "no", "problem": "30 gün"}', self.CONTEXT), "no: 30 gün")

    def test_an_answer_is_verified_with_the_sentence_the_grader_points_to(self):
        reply = json.dumps({"supported": "yes", "problem": "", "sentences": [1]})
        grader = Grader([reply])
        with patch("src.core.config.GRADER_MODE", "sentences"):
            result = verify_answer(grader, grader, CONTEXT, "Süre?", "İtiraz süresi 15 gündür.", SOURCES, "tr")
            # The number check still works on the cited sentence
            wrong = check_answer(Grader([reply]), CONTEXT, "Süre?", "İtiraz süresi 30 gündür.", SOURCES)
        self.assertEqual(result.level, VERIFIED)
        self.assertEqual(result.sources[0]["evidence"][0]["citation"], "Madde 54/10")
        self.assertIn('"sentences": []', grader.prompts[0])
        self.assertIn("[1] (10) Disiplin cezalarına", grader.contexts[0])
        self.assertFalse(wrong.passed)

    def test_a_garbled_quote_is_left_out_when_quotes_are_not_strict(self):
        garbled = "Soruşturma teşebbıs halinde yeniden açılır"
        reply = grade(quotes=[garbled, QUOTE])
        self.assertTrue(grade_from_quotes(reply, CONTEXT).startswith("no: quote not found"))
        self.assertEqual(grade_from_quotes(reply, CONTEXT, strict_quotes=False), "yes")
        # No quote is in the documents: still rejected
        self.assertNotEqual(grade_from_quotes(grade(quotes=[garbled]), CONTEXT, strict_quotes=False), "yes")
        with patch("src.core.config.GRADER_STRICT_QUOTES", False), patch("src.core.config.GRADER_MODE", "quotes"):
            self.assertTrue(check_answer(Grader([reply]), CONTEXT, "Süre?", "15 gün.", SOURCES).passed)


class TestRelevanceAndScript(unittest.TestCase):
    """GRADER_RELEVANCE_CHECK: the grader says whether the answer gives what is asked; ANSWER_SCRIPT_CHECK."""

    QUESTION = "Yıllık izin hakkı kaç gündür?"
    ANSWER = "Disiplin cezalarına itiraz edilebilir (Madde 54)."

    def setUp(self):
        patcher = patch("src.core.config.GRADER_RELEVANCE_CHECK", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def reply(answers="no"):
        verdict = {"supported": "yes", "problem": "", "answers_question": answers, "quotes": [QUOTE]}
        return json.dumps({**verdict, "sentences": [1]})

    def test_an_answer_beside_the_question_is_sent_back_once(self):
        grader = Grader([self.reply()])
        result = check_answer(grader, CONTEXT, self.QUESTION, self.ANSWER, SOURCES)
        self.assertFalse(result.passed)
        self.assertIn("does not give what the question asks for", result.objection)
        self.assertIn("answers_question", grader.prompts[0])
        # A refined answer is not sent back again, only marked; "not in the documents" answers the question
        again = check_answer(Grader([self.reply()]), CONTEXT, self.QUESTION, self.ANSWER, SOURCES, strict=False)
        self.assertEqual((again.passed, again.answers_question), (True, False))
        not_found = check_answer(Grader([self.reply()]), CONTEXT, self.QUESTION, message("no_context", "tr"), SOURCES)
        self.assertTrue(not_found.passed)
        self.assertTrue(check_answer(Grader([self.reply("yes")]), CONTEXT, "Süre?", "15 gün.", SOURCES).passed)

    def test_still_beside_the_question_after_refining_means_not_found(self):
        grader = Grader([self.reply(), self.reply()])
        result = verify_answer(Grader([], [self.ANSWER]), grader, CONTEXT, self.QUESTION, self.ANSWER, SOURCES, "tr")
        self.assertEqual(result.answer, message("no_context", "tr"))
        self.assertEqual(result.as_dict(), {"level": "unverified", "issues": ["not_found"]})
        # The editor finds the answer: verified as usual
        grader = Grader([self.reply(), self.reply("yes")])
        result = verify_answer(Grader([], ["15 gün."]), grader, CONTEXT, "Süre kaç gün?", self.ANSWER, SOURCES, "tr")
        self.assertEqual((result.level, result.answer), (VERIFIED, "15 gün."))

    def test_the_prompt_is_unchanged_when_the_check_is_off(self):
        grader = Grader([grade()])
        with patch("src.core.config.GRADER_RELEVANCE_CHECK", False):
            check_answer(grader, CONTEXT, "Süre?", "15 gün.", SOURCES)
        self.assertNotIn("answers_question", grader.prompts[0])

    def test_letters_of_another_script(self):
        self.assertTrue(foreign_script("İtiraz süresi 15 gündür. 条件下不符合规则"))
        self.assertFalse(foreign_script("İtiraz süresi 15 gündür (Madde 54/10): %50, â, ş."))
        # A script the documents use is not foreign
        self.assertFalse(foreign_script("Katsayı α ile gösterilir.", allowed="α katsayısı"))
        # The editor slipped into Chinese: the draft is kept
        editor = Grader([], ["15 gün. 不符合规则"])
        self.assertEqual(refine_answer(editor, CONTEXT, "Süre?", "30 gün.", "tr"), "30 gün.")
        with patch("src.core.config.ANSWER_SCRIPT_CHECK", False):
            editor = Grader([], ["15 gün. 不符合规则"])
            self.assertEqual(refine_answer(editor, CONTEXT, "Süre?", "30 gün.", "tr"), "15 gün. 不符合规则")


class TestVerifyAnswer(unittest.TestCase):
    def verify(self, answer, grades, refined=()):
        return verify_answer(Grader(grades, refined), Grader(grades), CONTEXT, "Süre?", answer, SOURCES, "tr")

    def test_verified_answers_carry_evidence(self):
        result = self.verify("İtiraz süresi 15 gündür.", [grade()])
        self.assertEqual((result.level, result.is_refined), (VERIFIED, False))
        self.assertEqual(result.sources[0]["evidence"][0]["citation"], "Madde 54/10")

    def test_a_refined_answer_that_passes_is_verified(self):
        grader = Grader([grade(), grade()])
        editor = Grader([], refined=["İtiraz süresi 15 gündür."])
        result = verify_answer(editor, grader, CONTEXT, "Süre?", "İtiraz süresi 30 gündür.", SOURCES, "tr")
        self.assertEqual((result.level, result.answer, result.is_refined), (VERIFIED, "İtiraz süresi 15 gündür.", True))

    def test_the_supported_part_is_shown_when_the_check_keeps_failing(self):
        answer = "İtiraz süresi on beş gündür. Ayrıca rektör bu süreyi 45 güne uzatabilir."
        with patch("src.core.config.GRADER_SECOND_OPINION", False):
            grader = Grader([grade("no", "45 gün", (QUOTE,)), grade("no", "45 gün", (QUOTE,))])
            editor = Grader([], refined=[answer])
            result = verify_answer(editor, grader, CONTEXT, "Süre?", answer, SOURCES, "tr")
        self.assertEqual((result.level, result.answer), (PARTIAL, "İtiraz süresi on beş gündür."))
        self.assertEqual(result.as_dict(), {"level": "partial", "issues": ["partial"]})

    def test_nothing_supported_falls_back(self):
        with patch("src.core.config.GRADER_SECOND_OPINION", False):
            grader = Grader([grade("no", "x", ()), grade("no", "x", ())])
            result = verify_answer(
                Grader([], ["Rektör 45 gün verir."]), grader, CONTEXT, "?", "Rektör 45 gün verir.", SOURCES, "tr"
            )
        self.assertEqual((result.level, result.answer), (UNVERIFIED, message("fallback", "tr")))

    def test_combined_answers_take_the_weakest_level(self):
        parts = [
            {"verification": {"level": "verified", "issues": ["transitional"]}},
            {"verification": {"level": "partial", "issues": ["partial"]}},
            {},
        ]
        self.assertEqual(_combined_verification(parts), {"level": "partial", "issues": ["transitional", "partial"]})
        self.assertEqual(_combined_verification([{}]), {})


class TestReviewList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        token, _ = create_access_token("admin", "admin")
        cls.admin = {"Authorization": f"Bearer {token}"}

    def setUp(self):
        api_main._rate_limit_store.clear()

    def test_unverified_answers_and_negative_feedback_are_listed_for_review(self):
        orchestrator = MagicMock()
        orchestrator.query.return_value = {
            "answer": "Kısmi cevap.",
            "sources": [],
            "active_agent": "doc_agent",
            "agents": ["doc_agent"],
            "verification": {"level": "partial", "issues": ["partial"]},
        }
        question = "İnceleme listesi test sorusu 7f3a?"
        with patch("src.api.routes.query.get_multi_agent_orchestrator", return_value=orchestrator):
            response = self.client.post("/api/v1/query", headers=self.admin, json={"question": question})
        self.assertEqual(response.json()["verification"]["level"], "partial")
        self.client.post(
            "/api/v1/feedback", headers=self.admin, json={"question": "Beğenilmeyen soru 7f3a", "feedback": "negative"}
        )
        items = self.client.get("/api/v1/admin/review", headers=self.admin).json()["items"]
        reasons = {item["reason"] for item in items if "7f3a" in str(item.get("detail"))}
        self.assertEqual(reasons, {"unverified", "negative_feedback"})
        viewer, _ = create_access_token("review_viewer", "viewer")
        self.assertIn(
            self.client.get("/api/v1/admin/review", headers={"Authorization": f"Bearer {viewer}"}).status_code,
            (401, 403),
        )


if __name__ == "__main__":
    unittest.main()
