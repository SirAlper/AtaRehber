"""Routing context for the supervisor (live database tables) and the compliance verdict rules."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents import db_agent as db_agent_module
from src.agent.multi_agent.sub_agents.compliance_agent import COMPLIANCE_SYSTEM_PROMPT, ComplianceAuditorAgent
from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.connectors.db_connector import DatabaseConnector
from src.connectors.sample_db import create_sample_sqlite_db
from src.rag.rag_engine import RAGEngine


def make_engine(chunks):
    """RAGEngine with fake models: chunks is a list of (text, cosine_similarity, reranker_score)."""
    engine = object.__new__(RAGEngine)
    engine.distance_space = "cosine"
    engine.embedding_model = MagicMock()
    engine.embedding_model.encode.return_value = MagicMock(tolist=lambda: [0.0])
    engine.collection = MagicMock()
    engine.collection.count.return_value = len(chunks)
    engine.collection.query.return_value = {
        "documents": [[text for text, _, _ in chunks]],
        "metadatas": [[{"source": f"doc{i}.txt", "chunk_index": 0} for i in range(len(chunks))]],
        "distances": [[1.0 - sim for _, sim, _ in chunks]],
    }
    engine.reranker = MagicMock()
    engine.reranker.predict.side_effect = lambda pairs: [
        next(score for text, _, score in chunks if text == pair[1]) for pair in pairs
    ]
    return engine


class ContextAgent(BaseSubAgent):
    name = "context_agent"
    description = "Agent with live routing context"

    def __init__(self, context="", fail=False):
        super().__init__(chat_model=MagicMock())
        self._context, self._fail = context, fail

    def get_routing_context(self):
        if self._fail:
            raise ConnectionError("database down")
        return self._context

    def execute(self, state):
        return {}


class TestRoutingContext(unittest.TestCase):
    def test_routing_context_is_added_to_supervisor_prompt(self):
        registry = AgentRegistry()
        registry.register(ContextAgent("Connected database tables: orders (id, total)."))
        prompt = registry.get_supervisor_prompt()
        self.assertIn("Agent with live routing context", prompt)
        self.assertIn("Connected database tables: orders (id, total).", prompt)

    def test_failing_routing_context_does_not_break_routing(self):
        registry = AgentRegistry()
        registry.register(ContextAgent(fail=True))
        self.assertIn("context_agent", registry.get_supervisor_prompt())

    def test_supervisor_sends_routing_context_to_llm(self):
        registry = AgentRegistry()
        registry.register(ContextAgent("Connected database tables: orders (id, total)."))
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='{"agent": "context_agent", "reason": "r", "direct_response": ""}')
        decision = SupervisorAgent(chat_model=llm, registry=registry).route({"question": "How many orders?"})
        self.assertEqual(decision["next_agent"], "context_agent")
        system_prompt = llm.invoke.call_args.args[0][0].content
        self.assertIn("orders (id, total)", system_prompt)


class TestDatabaseRoutingContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = create_sample_sqlite_db(os.path.join(self.tmp.name, "sample.db"))
        self.connector = DatabaseConnector(database_url=f"sqlite:///{db_path}", allowed_tables=[])

    def tearDown(self):
        self.connector.engine.dispose()
        self.tmp.cleanup()

    def test_table_overview_lists_columns(self):
        overview = self.connector.get_table_overview()
        self.assertEqual(sorted(overview), ["destek_talepleri", "satislar", "urunler"])
        self.assertIn("stok_adedi", overview["urunler"])
        self.assertEqual(
            self.connector.get_table_overview(max_tables=1, max_columns=2),
            {"destek_talepleri": ["talep_id", "talep_kodu"]},
        )

    def test_allowed_tables_limit_the_overview(self):
        restricted = DatabaseConnector(database_url=self.connector.database_url, allowed_tables=["urunler"])
        self.assertEqual(list(restricted.get_table_overview()), ["urunler"])
        restricted.engine.dispose()

    def test_db_agent_describes_tables_and_caches_them(self):
        agent = DatabaseAgent(chat_model=MagicMock(), db_connector=self.connector)
        context = agent.get_routing_context()
        self.assertIn("urunler (urun_id, sku, urun_adi, kategori, birim_fiyat, stok_adedi)", context)
        self.assertIn("satislar", context)

        with patch.object(self.connector, "get_table_overview", wraps=self.connector.get_table_overview) as overview:
            agent.get_routing_context()
            overview.assert_not_called()
            with patch.object(db_agent_module.time, "monotonic", return_value=10**9):
                agent.get_routing_context()
            overview.assert_called_once()

    def test_db_agent_without_connection_adds_nothing(self):
        disconnected = DatabaseConnector(database_url="")
        self.assertEqual(DatabaseAgent(chat_model=MagicMock(), db_connector=disconnected).get_routing_context(), "")


class TestComplianceVerdicts(unittest.TestCase):
    def test_prompt_offers_undetermined_verdict(self):
        self.assertIn("[UNDETERMINED]", COMPLIANCE_SYSTEM_PROMPT)
        self.assertIn("Base the verdict only on the rules above", COMPLIANCE_SYSTEM_PROMPT)
        # Organization-neutral: no corporate roles such as CISO are suggested
        self.assertNotIn("CISO", COMPLIANCE_SYSTEM_PROMPT)

    def test_no_relevant_policy_means_undetermined_without_llm_call(self):
        llm = MagicMock()
        engine = MagicMock()
        engine.search.return_value = {"context": "", "sources": []}
        result = ComplianceAuditorAgent(chat_model=llm, rag_engine=engine).execute(
            {"question": "Is parking allowed on the roof?", "agent_trace": []}
        )
        self.assertIn("[UNDETERMINED]", result["final_answer"])
        self.assertEqual(result["sources"], [])
        llm.invoke.assert_not_called()
