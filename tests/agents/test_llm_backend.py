import asyncio
import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import httpx
import openai
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from ollama import ResponseError

from src.agent import llm
from src.agent.prompts import with_thinking_guide
from src.api.main import app
from src.api.state import QueryConcurrencyManager
from src.auth.jwt_handler import create_access_token


def ollama_tags(*names):
    """Fake response of GET /api/tags."""
    body = json.dumps({"models": [{"name": n, "model": n} for n in names]}).encode()
    response = io.BytesIO(body)
    response.__enter__ = lambda self=response: self
    response.__exit__ = lambda *args: False
    return response


class TestOllamaChatModel(unittest.TestCase):
    def test_create_chat_model_uses_configured_ollama_settings(self):
        with (
            patch.object(llm, "OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch.object(llm, "OLLAMA_NUM_CTX", 8192),
            patch.object(llm, "OLLAMA_NUM_GPU", -1),
        ):
            model = llm.create_chat_model()
        self.assertIsInstance(model, ChatOllama)
        self.assertEqual(model.model, "qwen2.5:7b")
        self.assertEqual(model.base_url, "http://127.0.0.1:11434")
        self.assertEqual(model.num_ctx, 8192)
        self.assertEqual(model.temperature, 0.0)
        # OLLAMA_NUM_GPU unset: Ollama decides the GPU layers
        self.assertIsNone(model.num_gpu)

    def test_num_gpu_forces_gpu_layers(self):
        with patch.object(llm, "OLLAMA_NUM_GPU", 99):
            self.assertEqual(llm.create_chat_model().num_gpu, 99)

    def test_num_predict_limits_the_reply_length(self):
        with patch.object(llm, "OLLAMA_NUM_PREDICT", 1024):
            self.assertEqual(llm.create_chat_model().num_predict, 1024)

    def test_removed_huggingface_settings_are_reported(self):
        with (
            patch.dict("os.environ", {"LLM_BACKEND": "huggingface", "LLM_MODEL_ID": "Qwen/Qwen2.5-1.5B-Instruct"}),
            self.assertLogs(llm.logger, level="WARNING") as logs,
        ):
            llm.create_chat_model()
        self.assertIn("LLM_BACKEND, LLM_MODEL_ID", logs.output[0])

    def test_llm_backend_ollama_is_not_reported(self):
        with patch.dict("os.environ", {"LLM_BACKEND": "ollama"}), patch.object(llm.logger, "warning") as warning:
            llm.create_chat_model()
        warning.assert_not_called()

    def test_chat_model_replies_without_thinking_by_default(self):
        # None would let qwen3 think and write its thinking into the reply
        self.assertIs(llm.create_chat_model().reasoning, False)


def ollama_reply(content, done_reason="stop", thinking=""):
    """Fake ChatOllama._generate result."""
    message = AIMessage(content=content, additional_kwargs={"reasoning_content": thinking} if thinking else {})
    return ChatResult(generations=[ChatGeneration(message=message, generation_info={"done_reason": done_reason})])


class TestThinking(unittest.TestCase):
    def setUp(self):
        llm._thinking_support.clear()
        self.addCleanup(llm._thinking_support.clear)

    def _model(self, model="qwen3:8b", can_think=True):
        llm._thinking_support[model] = can_think
        with patch.object(llm, "OLLAMA_MODEL", model):
            return llm.create_chat_model()

    def test_thinking_tasks_think_with_sampling_and_their_own_token_limit(self):
        with (
            patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"answer"})),
            patch.object(llm, "OLLAMA_THINK_NUM_PREDICT", 2048),
            patch.object(llm, "OLLAMA_SEED", 42),
        ):
            model = llm.for_task(self._model(), "answer")
        self.assertTrue(llm.is_thinking(model))
        self.assertEqual((model.temperature, model.top_p, model.top_k), (0.6, 0.95, 20))
        self.assertEqual((model.num_predict, model.seed), (2048, 42))

    def test_other_tasks_use_the_model_as_is(self):
        base = self._model()
        with patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"answer"})):
            self.assertIs(llm.for_task(base, "router"), base)

    def test_all_makes_every_task_think_and_a_thinking_model_stops_for_other_tasks(self):
        with patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"all"})):
            thinking = llm.for_task(self._model(), "router")
        self.assertTrue(llm.is_thinking(thinking))
        with patch.object(llm, "OLLAMA_THINK_TASKS", frozenset()):
            direct = llm.for_task(thinking, "router")
        self.assertFalse(llm.is_thinking(direct))
        self.assertEqual((direct.temperature, direct.num_predict), (0.0, llm.OLLAMA_NUM_PREDICT))

    def test_models_that_cannot_think_and_test_doubles_do_not_think(self):
        with patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"answer"})):
            self.assertFalse(llm.is_thinking(llm.for_task(self._model("qwen2.5:7b", can_think=False), "answer")))
            double = MagicMock(spec=["invoke"])
            self.assertIs(llm.for_task(double, "answer"), double)

    def test_supports_thinking_reads_the_capabilities_of_the_model(self):
        show = io.BytesIO(json.dumps({"capabilities": ["completion", "tools", "thinking"]}).encode())
        show.__enter__ = lambda self=show: self
        show.__exit__ = lambda *args: False
        with patch("urllib.request.urlopen", return_value=show) as urlopen:
            self.assertTrue(llm.supports_thinking("qwen3:8b"))
            self.assertTrue(llm.supports_thinking("qwen3:8b"))
        urlopen.assert_called_once()

    def test_unreachable_ollama_is_asked_again_later(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            self.assertFalse(llm.supports_thinking("qwen3:8b"))
        self.assertNotIn("qwen3:8b", llm._thinking_support)

    def _thinking_model(self):
        with patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"answer"})):
            return llm.for_task(self._model(), "answer")

    def test_reply_cut_off_while_thinking_is_answered_again_without_thinking(self):
        calls = []

        def generate(model, messages, stop=None, run_manager=None, **kwargs):
            calls.append(model.reasoning)
            if model.reasoning:
                return ollama_reply("", done_reason="length", thinking="Madde 30'a bakalım...")
            return ollama_reply("Yaş haddi 67'dir.")

        with patch.object(ChatOllama, "_generate", autospec=True, side_effect=generate):
            reply = self._thinking_model().invoke("Emeklilik yaş haddi kaçtır?")
        self.assertEqual(calls, [True, False])
        self.assertEqual(reply.content, "Yaş haddi 67'dir.")

    def test_thinking_left_in_the_reply_is_removed(self):
        reply = ollama_reply("<think>\nMadde 30 diyor ki...\n</think>\n\nYaş haddi 67'dir.")
        with patch.object(ChatOllama, "_generate", autospec=True, return_value=reply):
            self.assertEqual(self._model().invoke("Soru").content, "Yaş haddi 67'dir.")

    def test_model_that_rejects_thinking_is_asked_without_it_from_then_on(self):
        calls = []

        def generate(model, messages, stop=None, run_manager=None, **kwargs):
            calls.append(model.reasoning)
            if model.reasoning:
                raise ResponseError('"qwen3:8b" does not support thinking', 400)
            return ollama_reply("Cevap")

        thinking = self._thinking_model()
        with patch.object(ChatOllama, "_generate", autospec=True, side_effect=generate):
            self.assertEqual(thinking.invoke("Soru").content, "Cevap")
        self.assertEqual(calls, [True, False])
        self.assertFalse(llm.supports_thinking("qwen3:8b"))

    def test_thinking_guide_is_added_only_for_a_thinking_model(self):
        messages = [SystemMessage(content="Rules"), HumanMessage(content="Question")]
        guided = with_thinking_guide(messages, self._thinking_model(), "answer")
        self.assertIn("While thinking", guided[0].content)
        self.assertEqual(guided[1:], messages[1:])
        self.assertIs(with_thinking_guide(messages, self._model(), "answer"), messages)


def json_response(data):
    """Fake urlopen response with a JSON body."""
    response = io.BytesIO(json.dumps(data).encode())
    response.__enter__ = lambda self=response: self
    response.__exit__ = lambda *args: False
    return response


def bad_request(text):
    request = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")
    return openai.BadRequestError(text, response=httpx.Response(400, request=request), body=None)


def openai_reply(content, finish_reason="stop"):
    """Fake ChatOpenAI._generate result."""
    return ChatResult(
        generations=[
            ChatGeneration(message=AIMessage(content=content), generation_info={"finish_reason": finish_reason})
        ]
    )


class TestVllmBackend(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(llm, "LLM_BACKEND", "vllm"),
            patch.object(llm, "VLLM_MODEL", "Qwen/Qwen3-8B"),
            patch.object(llm, "VLLM_BASE_URL", "http://localhost:8000/v1"),
            patch.object(llm, "OLLAMA_THINK_TASKS", frozenset({"answer"})),
            patch.object(llm, "OLLAMA_THINK_NUM_PREDICT", 2048),
            patch.object(llm, "OLLAMA_SEED", 42),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        llm._no_json_mode.clear()
        self.addCleanup(llm._no_json_mode.clear)

    def test_vllm_model_replies_without_thinking_by_default(self):
        model = llm.create_chat_model()
        self.assertIsInstance(model, llm.VllmChatModel)
        self.assertEqual((model.model_name, model.openai_api_base), ("Qwen/Qwen3-8B", "http://localhost:8000/v1"))
        self.assertFalse(llm.is_thinking(model))
        self.assertEqual(model.temperature, 0.0)
        self.assertEqual(model.max_tokens, llm.OLLAMA_NUM_PREDICT)
        self.assertEqual(model.extra_body, {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(llm.configured_models(), ["Qwen/Qwen3-8B"])

    def test_thinking_task_switches_qwen3_thinking_on_in_the_request(self):
        model = llm.for_task(llm.create_chat_model(), "answer")
        self.assertTrue(llm.is_thinking(model))
        self.assertEqual((model.temperature, model.top_p, model.max_tokens, model.seed), (0.6, 0.95, 2048, 42))
        payload = model._get_request_payload([HumanMessage(content="Soru")])
        self.assertEqual(payload["extra_body"], {"chat_template_kwargs": {"enable_thinking": True}, "top_k": 20})
        self.assertFalse(llm.is_thinking(llm.for_task(model, "router")))

    def test_json_mode_asks_for_a_json_object(self):
        bound = llm.json_mode(llm.create_chat_model())
        self.assertEqual(bound.kwargs, {"response_format": {"type": "json_object"}})

    def test_reply_cut_off_while_thinking_is_answered_again_without_thinking(self):
        calls = []

        def generate(model, messages, stop=None, run_manager=None, **kwargs):
            calls.append(model.enable_thinking)
            return openai_reply("", "length") if model.enable_thinking else openai_reply("Yaş haddi 67'dir.")

        with patch.object(ChatOpenAI, "_generate", autospec=True, side_effect=generate):
            reply = llm.for_task(llm.create_chat_model(), "answer").invoke("Emeklilik yaş haddi kaçtır?")
        self.assertEqual(calls, [True, False])
        self.assertEqual(reply.content, "Yaş haddi 67'dir.")

    def test_prompt_too_long_for_thinking_is_answered_without_thinking(self):
        calls = []

        def generate(model, messages, stop=None, run_manager=None, **kwargs):
            calls.append(model.enable_thinking)
            if model.enable_thinking:
                raise bad_request("This model's maximum context length is 8192 tokens.")
            return openai_reply("Cevap")

        with patch.object(ChatOpenAI, "_generate", autospec=True, side_effect=generate):
            self.assertEqual(llm.for_task(llm.create_chat_model(), "answer").invoke("Soru").content, "Cevap")
        self.assertEqual(calls, [True, False])

    def test_thinking_without_the_reasoning_parser_is_removed_from_the_reply(self):
        reply = openai_reply("Madde 30 diyor ki...\n</think>\n\nYaş haddi 67'dir.")
        with patch.object(ChatOpenAI, "_generate", autospec=True, return_value=reply):
            self.assertEqual(llm.create_chat_model().invoke("Soru").content, "Yaş haddi 67'dir.")

    def test_server_without_json_mode_is_asked_without_it(self):
        formats = []

        def generate(model, messages, stop=None, run_manager=None, **kwargs):
            formats.append(kwargs.get("response_format"))
            if "response_format" in kwargs:
                raise bad_request("guided decoding is not supported on this platform")
            return openai_reply('{"steps": []}')

        model = llm.json_mode(llm.create_chat_model())
        with patch.object(ChatOpenAI, "_generate", autospec=True, side_effect=generate):
            self.assertEqual(model.invoke("Soru").content, '{"steps": []}')
            model.invoke("Soru")
        self.assertEqual(formats, [{"type": "json_object"}, None, None])

    def test_check_reports_the_served_models(self):
        served = json_response({"data": [{"id": "Qwen/Qwen3-8B"}]})
        with patch("urllib.request.urlopen", return_value=served):
            self.assertIsNone(llm.check_llm())
        other = json_response({"data": [{"id": "Qwen/Qwen3-4B"}]})
        with patch("urllib.request.urlopen", return_value=other):
            self.assertIn("vllm serve Qwen/Qwen3-8B", llm.check_llm())
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            self.assertIn("vLLM server is not reachable", llm.check_llm())


class TestCheckOllama(unittest.TestCase):
    def test_ok_when_model_is_pulled(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch("urllib.request.urlopen", return_value=ollama_tags("qwen2.5:7b", "bge-m3:latest")),
        ):
            self.assertIsNone(llm.check_ollama())

    def test_untagged_model_name_matches_latest(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "llama3.1"),
            patch("urllib.request.urlopen", return_value=ollama_tags("llama3.1:latest")),
        ):
            self.assertIsNone(llm.check_ollama())

    def test_missing_model_tells_how_to_pull_it(self):
        with (
            patch.object(llm, "OLLAMA_MODEL", "qwen2.5:7b"),
            patch("urllib.request.urlopen", return_value=ollama_tags("qwen2.5-coder:7b")),
        ):
            problem = llm.check_ollama()
        self.assertIn("ollama pull qwen2.5:7b", problem)

    def test_unreachable_server(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            problem = llm.check_ollama()
        self.assertIn("not reachable", problem)


class TestStatsAndConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        token, _ = create_access_token("admin", "admin")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    def _stats(self, llm_problem):
        mock_engine = MagicMock()
        mock_engine.get_stats.return_value = {"total_chunks": 0, "total_documents": 0, "document_chunks": {}}
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = {"status": "not_configured"}
        with (
            patch("src.services.document_service.get_rag_engine", return_value=mock_engine),
            patch("src.services.document_service.get_db_connector", return_value=mock_connector),
            patch("src.services.document_service.check_llm", return_value=llm_problem),
        ):
            resp = self.client.get("/api/v1/stats", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_stats_reports_ollama_model_and_status(self):
        data = self._stats(None)
        self.assertEqual(data["llm_backend"], "ollama")
        self.assertIn("llm_model", data)
        self.assertEqual(data["llm_status"], "ok")

    def test_stats_reports_llm_problem(self):
        data = self._stats("Ollama model 'qwen2.5:7b' is not pulled. Run: ollama pull qwen2.5:7b")
        self.assertIn("ollama pull", data["llm_status"])

    def test_query_concurrency_gate_allows_parallel_requests(self):
        async def run_concurrency_test():
            active_count = 0
            max_simultaneous = 0
            manager = QueryConcurrencyManager()

            async def worker():
                nonlocal active_count, max_simultaneous
                async with manager:
                    active_count += 1
                    max_simultaneous = max(max_simultaneous, active_count)
                    await asyncio.sleep(0.05)
                    active_count -= 1

            await asyncio.gather(worker(), worker(), worker())
            self.assertGreaterEqual(max_simultaneous, 2)

        asyncio.run(run_concurrency_test())


if __name__ == "__main__":
    unittest.main()
