"""Database answers state only the query's values; compliance verdicts must rest on the retrieved rules."""

import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from src.agent.data_check import rows_table, unsupported_data_numbers
from src.agent.language import message
from src.agent.multi_agent.sub_agents.compliance_agent import ComplianceAuditorAgent
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.verification import unsupported_numbers

ROWS = [{"urun": "Kablo", "stok": 2, "fiyat": 1234.567}, {"urun": "Fare", "stok": 15, "fiyat": 349.9}]


class Scripted:
    """Chat model returning the given replies in order; records the messages it got."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.replies.pop(0))


def connector(rows=ROWS):
    db = MagicMock()
    db.is_connected = True
    db.dialect = "sqlite"
    db.get_schema_summary.return_value = "Table: urunler (urun, stok, fiyat)"
    db.execute_query.return_value = {"status": "success", "columns": ["urun", "stok", "fiyat"], "rows": rows}
    return db


class TestDataNumbers(unittest.TestCase):
    def test_values_are_recognized_in_turkish_and_english_formats_and_rounded(self):
        answer = "1. Kablo: 2 adet, 1.234,57 TL\n2. Fare: 15 adet, 349,90 TL (toplam 2 ürün)"
        self.assertEqual(unsupported_data_numbers(answer, ROWS, "Stoklar?", 2), [])
        self.assertEqual(unsupported_data_numbers("Kablo: 1,234.57", ROWS, "q", 2), [])

    def test_one_sign_for_thousands_and_decimals_is_read_too(self):
        self.assertEqual(unsupported_data_numbers("NovaERP: 120.000.00 TL", [{"fiyat": 120000.0}], "q", 1), [])

    def test_invented_or_miscopied_numbers_are_found(self):
        self.assertEqual(
            unsupported_data_numbers("Kablo stoğu 12, toplam 1.584,47 TL.", ROWS, "q", 2), ["12", "1.584,47"]
        )

    def test_numbers_of_the_question_and_stored_dates_count(self):
        rows = [{"tarih": "2026-01-15", "adet": 3}]
        self.assertEqual(
            unsupported_data_numbers("15.01.2026 tarihinde 3 adet; son 30 gün.", rows, "Son 30 gün?", 1), []
        )

    def test_rows_become_a_markdown_table(self):
        table = rows_table(["urun", "stok"], [{"urun": "A|B", "stok": 2}])
        self.assertEqual(table.splitlines(), ["| urun | stok |", "|---|---|", "| A\\|B | 2 |"])


class TestDatabaseAgentCheck(unittest.TestCase):
    def test_a_correct_explanation_is_kept(self):
        chat = Scripted("SELECT * FROM urunler", "Kablo: 2 adet, Fare: 15 adet.")
        out = DatabaseAgent(chat_model=chat, db_connector=connector()).execute({"question": "Stoklar?"})
        self.assertEqual(out["final_answer"], "Kablo: 2 adet, Fare: 15 adet.")
        self.assertEqual(out["verification"], {"level": "verified", "issues": ["data"]})
        self.assertEqual(out["agent_trace"][-1]["data_check"], "success")

    def test_a_wrong_number_is_corrected_once_with_the_objection(self):
        chat = Scripted("SELECT * FROM urunler", "Kablo: 20 adet.", "Kablo: 2 adet.")
        out = DatabaseAgent(chat_model=chat, db_connector=connector()).execute({"question": "Kablo stoğu?"})
        self.assertEqual(out["final_answer"], "Kablo: 2 adet.")
        self.assertIn("the number(s) 20 are not in the data", chat.calls[-1][-1].content)

    def test_when_it_stays_wrong_the_rows_are_shown_as_they_are(self):
        chat = Scripted("SELECT * FROM urunler", "Kablo: 20 adet.", "Kablo: 21 adet.")
        out = DatabaseAgent(chat_model=chat, db_connector=connector()).execute({"question": "Kablo stoğu?"})
        self.assertTrue(out["final_answer"].startswith(message("db_rows_fallback", "tr", count=2)))
        self.assertIn("| Kablo | 2 | 1234.567 |", out["final_answer"])
        self.assertNotIn("20", out["final_answer"])
        self.assertEqual(out["agent_trace"][-1]["data_check"], "mismatch")

    def test_a_step_can_look_up_what_an_earlier_step_found(self):
        chat = Scripted("SELECT * FROM urunler WHERE urun = 'Kablo'", "Kablo: 2 adet.")
        earlier = [{"agent": "doc_agent", "question": "Hangi ürün?", "answer": "Kablo"}]
        DatabaseAgent(chat_model=chat, db_connector=connector()).execute(
            {"question": "Bu ürünün stoğu?", "step_context": earlier}
        )
        self.assertIn("[doc_agent] Hangi ürün?\nKablo", chat.calls[0][-1].content)


RULES = "(1) Kişisel veriler, ilgili kişinin açık rızası olmadan üçüncü kişilere aktarılamaz."
VIOLATION = (
    "### 📌 1. Denetim Kararı\n**[VIOLATION / PROHIBITED]**\n\n### 📑 2. Dayanak\nMadde 8\n\n"
    "### 🔍 3. Risk\nCiddi risk.\n\n### 💡 4. Eylem\nRıza alın."
)
SUPPORTED = '{"supported": "yes", "problem": "", "quotes": ["açık rızası olmadan üçüncü kişilere aktarılamaz"]}'
REJECTED = '{"supported": "no", "problem": "Madde 8 bunu söylemiyor", "quotes": []}'


def compliance(chat, grader):
    rag = MagicMock()
    rag.search.return_value = {
        "context": RULES,
        "sources": [{"source": "kvkk.txt", "chunk_index": 0, "article": "Madde 8 – Aktarım", "content": RULES}],
    }
    return ComplianceAuditorAgent(chat_model=chat, rag_engine=rag, grader_model=grader)


class TestComplianceCheck(unittest.TestCase):
    def test_a_supported_verdict_shows_its_evidence(self):
        out = compliance(Scripted(VIOLATION), Scripted(SUPPORTED)).execute(
            {"question": "Öğrenci listesini rızasız bir firmaya gönderebilir miyim?"}
        )
        self.assertEqual(out["final_answer"], VIOLATION)
        self.assertEqual(out["verification"]["level"], "verified")
        self.assertTrue(out["sources"][0]["evidence"])

    def test_clock_times_match_however_they_are_written(self):
        quote = ["Yemekhane hafta içi 11.30'da açılır"]
        self.assertEqual(unsupported_numbers("11:30'da açılır, 14:00'te kapanır.", quote, "", ""), ["14.00"])

    def test_policy_sections_and_codes_are_references_not_numbers(self):
        cited = VIOLATION.replace("Madde 8", "KVKK-POL-02 Bölüm 2.1 ve 3.4 maddesi")
        out = compliance(Scripted(cited), Scripted(SUPPORTED)).execute({"question": "Gönderebilir miyim?"})
        self.assertEqual(out["verification"]["level"], "verified")
        self.assertEqual(unsupported_numbers("Bölüm 2.1, Section 4.1, SEC-POL-04: 30 gün", [], "", ""), ["30"])

    def test_only_the_verdict_and_the_rules_are_checked_not_the_risk_analysis(self):
        grader = Scripted(SUPPORTED)
        compliance(Scripted(VIOLATION), grader).execute({"question": "Gönderebilir miyim?"})
        checked = grader.calls[0][-1].content
        self.assertIn("[VIOLATION / PROHIBITED]", checked)
        self.assertNotIn("Ciddi risk", checked)

    def test_an_unsupported_verdict_is_revised_once_then_left_undetermined(self):
        chat = Scripted(VIOLATION, VIOLATION)
        # Each check: first verdict, then the second opinion
        grader = Scripted(REJECTED, REJECTED, REJECTED, REJECTED)
        out = compliance(chat, grader).execute({"question": "Gönderebilir miyim?"})
        self.assertIn("An auditor rejected the previous verdict", chat.calls[1][-1].content)
        self.assertEqual(out["final_answer"], message("compliance_unsupported", "tr"))
        self.assertEqual(out["verification"], {"level": "unverified", "issues": []})
        self.assertEqual(out["agent_trace"][-1]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
