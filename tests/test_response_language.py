"""Answers follow the language of the user's question (Turkish or English)."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

import pytest

from evals import metrics
from src.agent.language import (
    OTHER_LANGUAGE,
    detect_language,
    language_instruction,
    message,
    message_variants,
    response_language,
)
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.compliance_agent import ComplianceAuditorAgent
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.prompts import FALLBACK_RESPONSE, NO_CONTEXT_RESPONSE, build_rag_messages, build_refine_messages
from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Merhaba", "tr"),
        ("Peki saat kaçta?", "tr"),
        ("Onay gerekiyor mu?", "tr"),
        ("Kac urun var", "tr"),  # Turkish typed without Turkish characters
        ("İK onayı gerekir mi?", "tr"),
        ("Neler yapabilirsin?", "tr"),  # recognized by the verb suffix only
        ("The controller handles smaller requests", "en"),  # -ler endings are not a Turkish signal
        ("Is it allowed?", "en"),
        ("I want to copy files", "en"),
        ("What is İstanbul office's policy?", "en"),
        ("Based on the SQL query executed, there is 1 record. durum = 'çözüldü'", "en"),
        ("Ofiste evcil hayvan getirmek serbest mi?", "tr"),  # infinitive suffix + final question particle
        ("Bu da ne?", "tr"),
        # Other languages must not look Turkish (they share short words such as de, en, mi)
        ("¿Cuántos días de vacaciones tengo en la empresa?", OTHER_LANGUAGE),
        ("¿Puedo copiar mi lista de clientes en un USB?", OTHER_LANGUAGE),
        ("Combien de jours de congé ai-je dans l'entreprise?", OTHER_LANGUAGE),
        ("Quantos dias de férias eu tenho na empresa?", OTHER_LANGUAGE),
        ("Wie viele Urlaubstage habe ich in der Firma?", OTHER_LANGUAGE),
        ("我有多少天年假？", OTHER_LANGUAGE),
        ("मेरे पास कितनी छुट्टियां हैं?", OTHER_LANGUAGE),
        ("كم يوم إجازة لدي؟", OTHER_LANGUAGE),
        ("SR-2026-103?", None),
        ("", None),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_response_language_falls_back_to_earlier_questions_then_english():
    history = [{"question": "Destek talebi nasıl çözüldü?", "answer": "..."}]
    assert response_language("SR-2026-103?", history) == "tr"
    assert response_language("SR-2026-103?") == "en"
    assert response_language("How long?", history) == "en"


def test_unsupported_languages_are_mirrored_not_forced_to_english():
    assert response_language("¿Cuántos días de vacaciones tengo?") == OTHER_LANGUAGE
    instruction = language_instruction(OTHER_LANGUAGE)
    assert "same language as the user's question" in instruction
    assert "English" not in instruction
    # Fixed texts have no translation for other languages yet: English
    assert message("no_context", OTHER_LANGUAGE) == NO_CONTEXT_RESPONSE


def test_messages_are_localized_and_english_constants_stay_compatible():
    assert message("no_context", "tr") == "Bu bilgi kurum dokümanlarında bulunmuyor."
    assert message("no_context", "en") == NO_CONTEXT_RESPONSE
    assert FALLBACK_RESPONSE in message_variants("fallback")
    assert message("db_rows_fallback", "tr", count=3) == "Sorgu başarıyla çalıştı (3 kayıt bulundu):"
    assert message("greeting", "de") == message("greeting", "en")  # unknown language -> English


def test_turkish_fixed_answers_count_as_refusals_in_evaluation():
    for text in message_variants("no_context") + message_variants("fallback"):
        assert metrics.is_refusal(text), text


def test_prompt_builders_pin_the_language():
    rag = build_rag_messages("ctx", "Kaç gün?", language="tr")
    assert "Write your entire response in Turkish" in rag[0].content
    assert "Write your entire response" not in build_rag_messages("ctx", "q")[0].content

    refine = build_refine_messages("ctx", "Kaç gün?", "taslak", language="tr")
    assert message("no_context", "tr") in refine[0].content
    assert NO_CONTEXT_RESPONSE not in refine[0].content


def system_prompt_of(llm, call=0):
    return llm.invoke.call_args_list[call].args[0][0].content


class TestDocAgentLanguage(unittest.TestCase):
    def _agent(self, context, llm=None):
        engine = MagicMock()
        engine.search.return_value = {"context": context, "sources": [{"source": "hr.txt"}] if context else []}
        return DocumentRagAgent(chat_model=llm or MagicMock(), rag_engine=engine)

    def test_no_context_answer_in_question_language(self):
        agent = self._agent("")
        self.assertEqual(
            agent.execute({"question": "Otopark ücretli mi?"})["final_answer"], message("no_context", "tr")
        )
        self.assertEqual(agent.execute({"question": "Is parking free?"})["final_answer"], NO_CONTEXT_RESPONSE)

    def test_generation_prompt_names_the_language(self):
        llm = MagicMock()
        llm.invoke.side_effect = [MagicMock(content="20 gün."), MagicMock(content="yes")]
        self._agent("Yıllık izin 20 gündür.", llm).execute({"question": "Yıllık izin kaç gün?"})
        self.assertIn(language_instruction("tr"), system_prompt_of(llm))

    def test_unverifiable_answer_uses_localized_fallback(self):
        llm = MagicMock()
        llm.invoke.side_effect = [MagicMock(content="Uydurma."), MagicMock(content="no")] + [
            MagicMock(content="Yine uydurma."),
            MagicMock(content="no"),
        ]
        out = self._agent("Yıllık izin 20 gündür.", llm).execute({"question": "Yıllık izin kaç gün?"})
        self.assertEqual(out["final_answer"], message("fallback", "tr"))


class TestDbAgentLanguage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = create_sample_sqlite_db(os.path.join(self.tmp.name, "s.db"))
        self.connector = DatabaseConnector(database_url=f"sqlite:///{path}", allowed_tables=[])

    def tearDown(self):
        self.connector.engine.dispose()
        self.tmp.cleanup()

    def test_explanation_prompt_names_the_language(self):
        llm = MagicMock()
        llm.invoke.side_effect = [MagicMock(content="SELECT COUNT(*) FROM urunler"), MagicMock(content="5 ürün var.")]
        agent = DatabaseAgent(chat_model=llm, db_connector=self.connector)
        # A follow-up without language signal inherits the language of the earlier question
        state = {"question": "Ya SR-2026-101?", "chat_history": [{"question": "Kaç ürün var?", "answer": "5"}]}
        agent.execute(state)
        self.assertIn(language_instruction("tr"), system_prompt_of(llm, call=1))

    def test_not_connected_message_in_question_language(self):
        agent = DatabaseAgent(chat_model=MagicMock(), db_connector=DatabaseConnector(database_url=""))
        self.assertEqual(
            agent.execute({"question": "Kaç ürün var?"})["final_answer"], message("db_not_connected", "tr")
        )


class TestComplianceAgentLanguage(unittest.TestCase):
    def _agent(self, context, llm):
        engine = MagicMock()
        engine.search.return_value = {"context": context, "sources": [{"source": "sec.txt"}] if context else []}
        return ComplianceAuditorAgent(chat_model=llm, rag_engine=engine)

    def test_report_prompt_names_the_language_and_keeps_verdict_labels(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="### Karar\n[VIOLATION / PROHIBITED]")
        self._agent("USB yasaktır.", llm).execute({"question": "USB belleğe kopyalamam uygun mu?"})
        prompt = system_prompt_of(llm)
        self.assertIn(language_instruction("tr"), prompt)
        self.assertIn("copy the verdict label exactly", prompt)
        self.assertIn("### 📌 1. Denetim Kararı", prompt)  # the template itself is Turkish
        self.assertNotIn("Audit Verdict", prompt)

    def test_undetermined_report_in_question_language(self):
        out = self._agent("", MagicMock()).execute({"question": "Çatıya park etmem uygun mu?"})
        self.assertEqual(out["final_answer"], message("compliance_undetermined", "tr"))
        self.assertIn("[UNDETERMINED]", out["final_answer"])


class TestSupervisorLanguage(unittest.TestCase):
    def test_greeting_reply_in_question_language(self):
        supervisor = SupervisorAgent(chat_model=MagicMock(), registry=AgentRegistry())
        self.assertEqual(supervisor.route({"question": "Merhaba"})["final_answer"], message("greeting", "tr"))
        self.assertEqual(supervisor.route({"question": "hello"})["final_answer"], message("greeting", "en"))

    def test_unsupported_language_direct_response_mirrors_the_question(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='{"agent": "finish", "reason": "meta", "direct_response": "..."}')
        SupervisorAgent(chat_model=llm, registry=AgentRegistry()).route({"question": "¿Qué puedes hacer por mí?"})
        self.assertIn("written in the language of the user's question", system_prompt_of(llm))

    def test_direct_response_language_is_requested(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='{"agent": "finish", "reason": "meta", "direct_response": "..."}')
        SupervisorAgent(chat_model=llm, registry=AgentRegistry()).route({"question": "Neler yapabilirsin?"})
        self.assertIn("written in Turkish", system_prompt_of(llm))


if __name__ == "__main__":
    unittest.main()
