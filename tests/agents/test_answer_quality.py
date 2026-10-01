"""Answers from the documents: follow-up rewriting, evidence and citations, cache, progress, optional modes."""

import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agent.answer_cache import answer_cache, normalize_question
from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent, needs_rewrite
from src.agent.prompts import SYSTEM_PROMPT_GRADER_QUOTES, SYSTEM_PROMPT_REWRITE, split_evidence
from src.rag.evidence import attach_evidence, citation, display_text

CONTEXT = (
    "[YÖNETMELİK | Madde 30 – Ek süreler]\n"
    "(1) Lisans programları azami yedi yılda tamamlanır.\n\n"
    "(2) Azami süre sonunda son sınıf öğrencilerine başarısız oldukları bütün dersler için iki ek sınav hakkı verilir."
)
SOURCE = {"source": "yonetmelik.txt", "chunk_index": 4, "article": "Madde 30 – Ek süreler", "content": CONTEXT}
GRADE_YES = (
    '{"supported": "yes", "problem": "", '
    '"quotes": ["son sınıf öğrencilerine başarısız oldukları bütün dersler için iki ek sınav hakkı verilir"]}'
)


class ScriptedModel:
    """Answers by prompt type: grader -> next grade, rewrite -> rewritten query, otherwise the next answer."""

    def __init__(self, answers, grades=(GRADE_YES,), rewrite="rewritten query"):
        self.answers, self.grades, self.rewrite = list(answers), list(grades), rewrite
        self.calls = []

    def bind(self, **kwargs):
        return self

    def bind_tools(self, tools):
        self.tools = [tool.name for tool in tools]
        return self

    def invoke(self, messages):
        system = messages[0].content
        self.calls.append(system[:40])
        if system.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
            return AIMessage(content=self.grades.pop(0))
        if system.startswith(SYSTEM_PROMPT_REWRITE):
            return AIMessage(content=self.rewrite)
        return self.answers.pop(0)


def engine(version=0):
    mock = MagicMock()
    mock.index_version = version
    mock.search.return_value = {"context": CONTEXT, "sources": [dict(SOURCE)]}
    return mock


class TestFollowUps(unittest.TestCase):
    def test_short_or_referring_follow_ups_are_rewritten(self):
        history = [{"question": "Lisans programı en çok kaç yılda biter?", "answer": "Yedi yılda."}]
        self.assertTrue(needs_rewrite("Peki doktora için?", history))
        self.assertTrue(needs_rewrite("Bunun için başvuru süresi ne kadar ve nereye yapılır?", history))
        self.assertFalse(needs_rewrite("Öğretim üyelerinin emeklilik yaş haddi kanuna göre kaç yaştır?", history))
        self.assertFalse(needs_rewrite("Peki doktora için?", []))

    def test_the_rewritten_query_is_searched(self):
        rag = engine()
        model = ScriptedModel([AIMessage(content="Doktora için azami süre ...")], rewrite="Doktora azami süre")
        agent = DocumentRagAgent(chat_model=model, rag_engine=rag)
        history = [{"question": "Lisans programı en çok kaç yılda biter?", "answer": "Yedi yılda."}]
        agent.execute({"question": "Peki doktora için?", "chat_history": history})
        self.assertEqual(rag.search.call_args.args[0], "Doktora azami süre")


class TestEvidence(unittest.TestCase):
    def test_answers_carry_the_quoted_sentence_with_article_and_paragraph(self):
        model = ScriptedModel([AIMessage(content="İki ek sınav hakkı verilir.")])
        out = DocumentRagAgent(chat_model=model, rag_engine=engine()).execute({"question": "Kaç ek sınav hakkı var?"})
        source = out["sources"][0]
        self.assertTrue(source["used"])
        self.assertEqual(source["evidence"][0]["citation"], "Madde 30/2")
        self.assertTrue(source["evidence"][0]["text"].startswith("(2) Azami süre sonunda"))

    def test_unverified_answers_have_no_evidence(self):
        no = '{"supported": "no", "problem": "üç", "quotes": []}'
        model = ScriptedModel([AIMessage(content="Üç hak."), AIMessage(content="Üç hak.")], grades=[no, no])
        out = DocumentRagAgent(chat_model=model, rag_engine=engine()).execute({"question": "Kaç ek sınav hakkı?"})
        self.assertNotIn("evidence", out["sources"][0])

    def test_quotes_are_matched_to_the_original_sentence(self):
        # A copy that drops a word still finds its sentence; unrelated text finds nothing
        sources = attach_evidence([SOURCE], ["öğrencilerine bütün dersler için iki ek sınav hakkı", "tamamen başka"])
        self.assertEqual(len(sources[0]["evidence"]), 1)
        self.assertEqual(display_text(CONTEXT).splitlines()[0], "(1) Lisans programları azami yedi yılda tamamlanır.")
        self.assertEqual(citation({"article": "Madde 30 – Ek süreler"}, "(1) a\n(2) b", 8), "Madde 30/2")
        self.assertEqual(citation({"article": ""}, "metin", 0), "")


class TestAnswerCache(unittest.TestCase):
    def setUp(self):
        answer_cache.clear()
        patcher = patch("src.core.config.ANSWER_CACHE_SIZE", 10)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(answer_cache.clear)

    def ask(self, rag, question="Kaç ek sınav hakkı var?", model=None, user=None):
        model = model or ScriptedModel([AIMessage(content="İki ek sınav hakkı verilir.")])
        agent = DocumentRagAgent(chat_model=model, rag_engine=rag)
        return agent.execute({"question": question, "user": user}), model

    def test_the_same_first_question_is_answered_from_the_cache(self):
        rag = engine()
        first, _ = self.ask(rag)
        second, model = self.ask(rag, question="  kaç ek sınav hakkı VAR ")
        self.assertEqual(second["final_answer"], first["final_answer"])
        self.assertEqual(second["agent_trace"][-1]["action"], "cache_hit")
        self.assertEqual(model.calls, [], "no model call for a cached answer")
        self.assertEqual(rag.search.call_count, 1)

    def test_changed_documents_or_other_access_are_not_answered_from_the_cache(self):
        rag = engine()
        self.ask(rag)
        rag.index_version = 1  # a document was uploaded, deleted, or its access changed
        out, _ = self.ask(rag)
        self.assertEqual(out["agent_trace"][-1]["action"], "retrieval_and_generation")
        student = {"username": "o", "role": "viewer", "groups": ["ogrenci"]}
        out, _ = self.ask(rag, user=student)
        self.assertEqual(out["agent_trace"][-1]["action"], "retrieval_and_generation")

    def test_unverified_answers_and_follow_ups_are_not_cached(self):
        no = '{"supported": "no", "problem": "x", "quotes": []}'
        rag = engine()
        model = ScriptedModel([AIMessage(content="a"), AIMessage(content="b")], grades=[no, no])
        self.ask(rag, model=model)
        self.assertEqual(len(answer_cache), 0)
        self.assertEqual(normalize_question("İzin nedir?"), normalize_question("izin nedir"))


class TestProgressAndModes(unittest.TestCase):
    def test_streaming_reports_the_stages(self):
        model = ScriptedModel([AIMessage(content="İki ek sınav hakkı verilir.")])
        registry = AgentRegistry()
        registry.register(DocumentRagAgent(chat_model=model, rag_engine=engine()))
        orchestrator = MultiAgentOrchestrator(chat_model=model, registry=registry, checkpointer=MemorySaver())
        events = list(orchestrator.stream_events("Kaç ek sınav hakkı var?", forced_agent="doc_agent"))
        stages = [e["stage"] for e in events if e["type"] == "progress"]
        self.assertEqual(stages, ["searching", "writing", "verifying"])
        self.assertEqual(events[-1]["sources"][0]["evidence"][0]["citation"], "Madde 30/2")

    def test_evidence_first_replies_are_split(self):
        reply = 'EVIDENCE: "bütün dersler için iki ek sınav hakkı verilir"\nANSWER: İki ek sınav hakkı verilir.'
        self.assertEqual(
            split_evidence(reply), (["bütün dersler için iki ek sınav hakkı verilir"], "İki ek sınav hakkı verilir.")
        )
        self.assertEqual(split_evidence("Düz cevap."), ([], "Düz cevap."))
        model = ScriptedModel([AIMessage(content=reply)])
        with patch("src.core.config.ANSWER_EVIDENCE_FIRST", True):
            out = DocumentRagAgent(chat_model=model, rag_engine=engine()).execute({"question": "Kaç ek sınav?"})
        self.assertEqual(out["final_answer"], "İki ek sınav hakkı verilir.")

    def test_doc_agent_can_compute_with_tools(self):
        grade = '{"supported": "yes", "problem": "", "quotes": []}'
        call = AIMessage(content="", tool_calls=[{"name": "calculator", "args": {"expression": "2020+7"}, "id": "c1"}])
        model = ScriptedModel([call, AIMessage(content="En erken 2027'de.")], grades=[grade])
        with patch("src.core.config.DOC_AGENT_TOOLS", True):
            out = DocumentRagAgent(chat_model=model, rag_engine=engine()).execute(
                {"question": "2020'den 7 yıl sonrası?"}
            )
        self.assertEqual(out["final_answer"], "En erken 2027'de.")
        self.assertEqual(model.tools, ["calculator", "date_calculator"])
        self.assertEqual(out["agent_trace"][-1]["tools_called"], ["calculator"])


if __name__ == "__main__":
    unittest.main()
