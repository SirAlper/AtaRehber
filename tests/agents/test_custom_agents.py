"""Custom agents defined in the web UI: definitions, store, registry sync, tool calling, answer check, API."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import ValidationError

from src.agent.language import message
from src.agent.multi_agent.custom_agents import (
    CustomAgent,
    CustomAgentConfig,
    CustomAgentStore,
    sync_custom_agents,
)
from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
from src.agent.multi_agent.registry import AgentRegistry
from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
from src.agent.multi_agent.tools import calculate, date_calculation
from src.agent.prompts import SYSTEM_PROMPT_GRADER_QUOTES
from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.auth.user_store import user_store


def definition(name="not_asistani", tools=("calculator",), **extra):
    return {
        "name": name,
        "display_name": "Not Asistanı",
        "description": "Not ortalaması ve harf notu hesaplama soruları",
        "instructions": "Öğrencilerin not ortalamasını hesapla ve sonucu açıkla.",
        "tools": list(tools),
        "enabled": True,
        **extra,
    }


# The scripted graders of this module reply in the quotes format without "answers_question"; the defaults
# (GRADER_MODE=sentences, GRADER_RELEVANCE_CHECK) are tested in test_verification.py and
# test_specialist_agents.py
_grader_format = [
    patch("src.core.config.GRADER_MODE", "quotes"),
    patch("src.core.config.GRADER_RELEVANCE_CHECK", False),
]


def setUpModule():
    for patcher in _grader_format:
        patcher.start()


def tearDownModule():
    for patcher in _grader_format:
        patcher.stop()


class FakeToolModel:
    """Chat model that replies from a script; tool calls are AIMessages with tool_calls."""

    def __init__(self, replies, grades=()):
        self.replies = list(replies)
        self.grades = list(grades)
        self.bound = None
        self.prompts = []

    def bind_tools(self, tools):
        self.bound = [tool.name for tool in tools]
        return self

    def bind(self, **kwargs):  # json_mode
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        if messages[0].content.startswith(SYSTEM_PROMPT_GRADER_QUOTES):
            return AIMessage(content=self.grades.pop(0))
        return self.replies.pop(0)


def call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


class TestTools(unittest.TestCase):
    def test_calculator_evaluates_arithmetic_without_running_code(self):
        self.assertEqual(calculate("(40*0,3)+(70*0,7)"), "(40*0,3)+(70*0,7) = 61")
        self.assertEqual(calculate("round(2.456,2)"), "round(2.456,2) = 2.46")
        for unsafe in ('__import__("os")', "().__class__", "9**999999", "x+1", "True+1"):
            with self.assertRaises(ValueError, msg=unsafe):
                calculate(unsafe)

    def test_date_calculation(self):
        self.assertIn("= 2026-10-13", date_calculation("28.09.2026", days=15))
        # Month ends are clamped
        self.assertIn("= 2026-02-28", date_calculation("2026-01-31", months=1))
        self.assertIn(": 115 days", date_calculation("2026-09-01", end_date="2026-12-25"))


class TestDefinitionsAndStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = CustomAgentStore(os.path.join(self.tmp, "custom_agents.json"))

    def test_invalid_definitions_are_rejected(self):
        for bad in (
            {"name": "Not Asistanı"},
            {"name": "supervisor"},
            {"tools": ["internet"]},
            {"description": "kısa"},
        ):
            with self.assertRaises(ValidationError, msg=bad):
                CustomAgentConfig(**{**definition(), **bad})
        self.assertEqual(CustomAgentConfig(**definition(tools=["dates", "dates"])).tools, ["dates"])

    def test_save_keeps_the_creator_and_protects_built_in_names(self):
        self.store.save(CustomAgentConfig(**definition()), "admin")
        updated = self.store.save(CustomAgentConfig(**definition(enabled=False)), "editor_admin")
        self.assertEqual(
            (updated["created_by"], updated["updated_by"], updated["enabled"]), ("admin", "editor_admin", False)
        )
        self.assertEqual(len(self.store.all()), 1)
        with self.assertRaises(ValueError):
            self.store.save(CustomAgentConfig(**definition(name="doc_agent")), "admin", reserved={"doc_agent"})
        self.assertTrue(self.store.delete("not_asistani"))
        self.assertFalse(self.store.delete("not_asistani"))

    def test_sync_registers_updates_and_removes_agents(self):
        registry = AgentRegistry()
        registry.register(DocumentRagAgent(chat_model=MagicMock(), rag_engine=MagicMock()))
        self.store.save(CustomAgentConfig(**definition()), "admin")
        # A stale file cannot replace a built-in agent
        self.store._save(self.store.all() + [definition(name="doc_agent")])
        self.assertEqual(sync_custom_agents(registry, self.store), 1)
        self.assertIsInstance(registry.get("not_asistani"), CustomAgent)
        self.assertIsInstance(registry.get("doc_agent"), DocumentRagAgent)
        self.assertIn("Not ortalaması ve harf notu", registry.get_supervisor_prompt())

        version = registry.version
        sync_custom_agents(registry, self.store)
        self.assertEqual(registry.version, version, "unchanged definitions are not re-registered")

        self.store.save(CustomAgentConfig(**definition(enabled=False)), "admin")
        sync_custom_agents(registry, self.store)
        self.assertNotIn("not_asistani", [a.name for a in registry.list_available_agents()])

        self.store.delete("not_asistani")
        sync_custom_agents(registry, self.store)
        self.assertIsNone(registry.get("not_asistani"))


class TestCustomAgentRuns(unittest.TestCase):
    def test_the_model_calls_the_calculator_and_answers(self):
        model = FakeToolModel([call("calculator", {"expression": "40*0.4+80*0.6"}), AIMessage(content="Ortalama 64.")])
        agent = CustomAgent(definition(), chat_model=model)
        out = agent.execute({"question": "Vizem 40 finalim 80, ortalamam kaç?"})
        self.assertEqual(out["final_answer"], "Ortalama 64.")
        self.assertEqual(model.bound, ["calculator"])
        self.assertEqual(out["agent_trace"][-1]["tools_called"], ["calculator"])
        # The tool result went back to the model
        self.assertIn("= 64", model.prompts[1][-1].content)
        # The administrator's instructions and the language rule are in the system prompt
        self.assertIn("not ortalamasını hesapla", model.prompts[0][0].content)
        self.assertNotIn("hallucination_grade", out)

    def test_an_agent_without_tools_just_answers(self):
        model = FakeToolModel([AIMessage(content="Dilekçe taslağı: ...")])
        out = CustomAgent(definition(tools=()), chat_model=model).execute({"question": "Dilekçe yaz"})
        self.assertEqual(out["final_answer"], "Dilekçe taslağı: ...")
        self.assertIsNone(model.bound)

    def document_run(self, grades):
        engine = MagicMock()
        engine.search.return_value = {
            "context": "[YÖNETMELİK | Madde 22] Ara sınav sonuçları yedi gün içinde ilan edilir.",
            "sources": [{"source": "yonetmelik.txt", "chunk_index": 3, "article": "Madde 22"}],
        }
        model = FakeToolModel(
            [
                call("search_documents", {"query": "ara sınav sonuç ilan süresi"}),
                call("date_calculator", {"start_date": "2026-11-02", "days": 7}),
                AIMessage(content="Sonuçlar en geç 2026-11-09 tarihinde ilan edilir (Madde 22)."),
                AIMessage(content="Düzeltilmiş cevap."),
            ],
            grades=grades,
        )
        agent = CustomAgent(definition(tools=("documents", "dates")), chat_model=model)
        user = {"username": "ogrenci", "role": "viewer", "groups": []}
        with patch("src.api.state.get_rag_engine", return_value=engine):
            out = agent.execute({"question": "2 Kasım'daki sınavın sonucu en geç ne zaman ilan edilir?", "user": user})
        return out, engine, model

    def test_document_answers_are_checked_with_every_tool_result_as_context(self):
        yes = '{"supported": "yes", "problem": "", "quotes": ["Ara sınav sonuçları yedi gün içinde ilan edilir."]}'
        out, engine, model = self.document_run([yes])
        self.assertEqual(out["final_answer"], "Sonuçlar en geç 2026-11-09 tarihinde ilan edilir (Madde 22).")
        self.assertEqual(out["hallucination_grade"], "yes")
        self.assertEqual(out["sources"][0]["article"], "Madde 22")
        # The user's access groups limit the search
        self.assertEqual(engine.search.call_args.kwargs["allowed_groups"], ["ziyaretci"])
        grader_context = model.prompts[-1][1].content
        self.assertIn("= 2026-11-09", grader_context, "the computed date is context for the check")

    def test_an_unsupported_document_answer_falls_back(self):
        no = '{"supported": "no", "problem": "30 gün", "quotes": []}'
        out, _, _ = self.document_run([no, no])
        self.assertEqual(out["final_answer"], message("fallback", "tr"))
        self.assertTrue(out["is_refined"])
        self.assertEqual(out["agent_trace"][-1]["status"], "unverified")

    def test_the_orchestrator_routes_to_a_custom_agent(self):
        model = FakeToolModel([call("calculator", {"expression": "2+2"}), AIMessage(content="Sonuç 4.")])
        registry = AgentRegistry()
        registry.register(CustomAgent(definition(), chat_model=model))
        orchestrator = MultiAgentOrchestrator(chat_model=MagicMock(), registry=registry, checkpointer=MemorySaver())
        result = orchestrator.query("2 artı 2 kaç?", forced_agent="not_asistani")
        self.assertEqual((result["answer"], result["active_agent"]), ("Sonuç 4.", "not_asistani"))


class TestCustomAgentsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        admin, _ = create_access_token("admin", "admin")
        try:
            user_store.create_user("custom_agent_viewer", "Passw0rdX", "viewer")
        except ValueError:
            pass  # created by an earlier run
        viewer, _ = create_access_token("custom_agent_viewer", "viewer")
        cls.admin = {"Authorization": f"Bearer {admin}"}
        cls.viewer = {"Authorization": f"Bearer {viewer}"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        store = CustomAgentStore(os.path.join(self.tmp, "custom_agents.json"))
        registry = AgentRegistry()
        registry.register(DocumentRagAgent(chat_model=MagicMock(), rag_engine=MagicMock()))
        for target in ("src.api.routes.admin.custom_agent_store",):
            patcher = patch(target, store)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.registry = registry
        patcher = patch("src.api.routes.admin.agent_registry", registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        sync = patch("src.api.routes.admin.sync_custom_agents", side_effect=lambda: sync_custom_agents(registry, store))
        sync.start()
        self.addCleanup(sync.stop)
        built_in = patch("src.api.routes.admin.built_in_agent_names", return_value={"doc_agent"})
        built_in.start()
        self.addCleanup(built_in.stop)

    def test_admin_creates_lists_and_deletes_an_agent(self):
        response = self.client.put("/api/v1/admin/custom-agents/not_asistani", headers=self.admin, json=definition())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsInstance(self.registry.get("not_asistani"), CustomAgent)
        listed = self.client.get("/api/v1/admin/custom-agents", headers=self.admin).json()["agents"]
        self.assertEqual(
            [(a["name"], a["available"], a["created_by"]) for a in listed], [("not_asistani", True, "admin")]
        )
        tools = self.client.get("/api/v1/admin/agent-tools", headers=self.admin).json()["tools"]
        self.assertEqual([t["name"] for t in tools], ["documents", "calculator", "dates", "database"])
        self.assertEqual(
            self.client.delete("/api/v1/admin/custom-agents/not_asistani", headers=self.admin).status_code, 200
        )
        self.assertIsNone(self.registry.get("not_asistani"))
        self.assertEqual(
            self.client.delete("/api/v1/admin/custom-agents/not_asistani", headers=self.admin).status_code, 404
        )

    def test_invalid_requests_are_rejected(self):
        url = "/api/v1/admin/custom-agents"
        self.assertEqual(self.client.put(f"{url}/baska_ad", headers=self.admin, json=definition()).status_code, 400)
        self.assertEqual(
            self.client.put(f"{url}/doc_agent", headers=self.admin, json=definition(name="doc_agent")).status_code, 400
        )
        self.assertEqual(
            self.client.put(f"{url}/not_asistani", headers=self.admin, json=definition(tools=["internet"])).status_code,
            422,
        )
        self.assertEqual(
            self.client.put(f"{url}/not_asistani", headers=self.viewer, json=definition()).status_code, 403
        )
        self.assertEqual(self.client.get(url, headers=self.viewer).status_code, 403)


if __name__ == "__main__":
    unittest.main()
