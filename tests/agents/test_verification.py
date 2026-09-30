"""Answer check: second opinion, number and transitional-article checks, partial answers, levels, review list."""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.agent.language import message
from src.agent.multi_agent.orchestrator_graph import _combined_verification
from src.agent.prompts import SYSTEM_PROMPT_GRADER_QUOTES
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
    return json.dumps({"supported": supported, "problem": problem, "quotes": list(quotes)}, ensure_ascii=False)


class Grader:
    """Scripted grader and editor: grader prompts get the next grade, the editor the next refined answer."""

    def __init__(self, grades, refined=()):
        self.grades, self.refined, self.prompts = list(grades), list(refined), []

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        if messages[0].content.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
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
        return check_answer(Grader(grades), CONTEXT, question, answer, sources, strict_transitional=strict)

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
