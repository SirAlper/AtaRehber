"""Chat model factory. The LLM runs in a separate server, Ollama or vLLM (LLM_BACKEND); no model weights are loaded
in this process.

Thinking models (qwen3) think before they reply. Every call states whether it thinks: the tasks listed in
OLLAMA_THINK_TASKS do (for_task), all others reply directly. The thinking is returned apart from the reply, so
the reply holds only the answer.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

import openai
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from ollama import ResponseError

from src.core.config import (
    LLM_BACKEND,
    LLM_STATUS_CACHE_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_GRADER_MODEL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_GPU,
    OLLAMA_NUM_PREDICT,
    OLLAMA_ROUTER_MODEL,
    OLLAMA_SEED,
    OLLAMA_THINK_NUM_PREDICT,
    OLLAMA_THINK_TASKS,
    VLLM_API_KEY,
    VLLM_BASE_URL,
    VLLM_MODEL,
)
from src.core.logger import get_logger

logger = get_logger("LLM")

BACKENDS = ("ollama", "vllm")
# Settings of the removed in-process HuggingFace backend; warn if a .env still sets them
REMOVED_SETTINGS = ("LLM_MODEL_ID", "LLM_MODEL_DIR")

# Sampling of thinking calls as Qwen recommends for qwen3: greedy decoding (temperature 0) makes the thinking
# repeat itself endlessly. Calls without thinking stay greedy, so their replies are repeatable.
THINKING_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
DIRECT_SAMPLING = {"temperature": 0.0, "top_p": None, "top_k": None}

# Thinking left in the reply itself: a server that does not separate it (Ollama without the "think" setting, vLLM
# without --reasoning-parser). "<think>...</think>", or only its end when the template opened the block.
_THINK_BLOCK = re.compile(r"^\s*(?:<think>.*?(?:</think>\s*|$)|[^<]*?</think>\s*)", re.DOTALL)


def strip_thinking(text: str) -> str:
    """The reply without a thinking block at its start."""
    return _THINK_BLOCK.sub("", text, count=1) if "think>" in text else text


# Whether a model can think, by model name: Ollama lists "thinking" among its capabilities (/api/show) and
# rejects thinking calls to other models
_thinking_support: dict = {}


def supports_thinking(model: str) -> bool:
    """Whether Ollama can run this model with thinking; asked once per model (False while Ollama is unreachable)."""
    if model not in _thinking_support:
        request = urllib.request.Request(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/show",
            data=json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                capabilities = json.load(response).get("capabilities") or []
        except (urllib.error.URLError, OSError, ValueError) as e:
            logger.warning(f"[LLM] Could not ask Ollama whether '{model}' can think ({e}); replying without thinking.")
            return False
        _thinking_support[model] = "thinking" in capabilities
    return _thinking_support[model]


class _ThinkingFallback:
    """Answers a thinking call again without thinking when the thinking used up its tokens or the call failed
    because of the thinking, and removes a thinking block left in the reply. Mixed into the chat models below."""

    def _model_label(self) -> str:
        raise NotImplementedError

    def _thinks(self, kwargs: dict) -> bool:
        raise NotImplementedError

    def _without_thinking(self):
        raise NotImplementedError

    def _limit_reached(self, generation) -> bool:
        raise NotImplementedError

    def _failed_by_thinking(self, error: Exception) -> bool:
        """Whether a failed thinking call may succeed without thinking."""
        return False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        thinking = self._thinks(kwargs)
        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
        except Exception as e:
            if not thinking or not self._failed_by_thinking(e):
                raise
            logger.warning(f"[LLM] Thinking call to '{self._model_label()}' failed ({e}); asking without thinking.")
            kwargs.pop("reasoning", None)
            return self._without_thinking()._generate(messages, stop, run_manager, **kwargs)

        generation = result.generations[0]
        if thinking and self._limit_reached(generation):
            thought = len(str(generation.message.additional_kwargs.get("reasoning_content") or ""))
            logger.warning(
                f"[LLM] '{self._model_label()}' reached the token limit of a thinking call ({thought} characters of "
                "thinking returned); answering again without thinking."
            )
            kwargs.pop("reasoning", None)
            return self._without_thinking()._generate(messages, stop, run_manager, **kwargs)
        if isinstance(generation.message.content, str) and "think>" in generation.message.content:
            generation.message.content = strip_thinking(generation.message.content)
            generation.text = generation.message.content
        return result


class OllamaChatModel(_ThinkingFallback, ChatOllama):
    """ChatOllama whose thinking calls (reasoning=True) fall back to a direct reply (see _ThinkingFallback); a
    model Ollama says cannot think is asked without thinking from then on."""

    def _model_label(self) -> str:
        return self.model

    def _thinks(self, kwargs: dict) -> bool:
        return kwargs.get("reasoning", self.reasoning) is True

    def _without_thinking(self) -> "OllamaChatModel":
        return self.model_copy(update={"reasoning": False, "num_predict": OLLAMA_NUM_PREDICT, **DIRECT_SAMPLING})

    def _limit_reached(self, generation) -> bool:
        return (generation.generation_info or {}).get("done_reason") == "length"

    def _failed_by_thinking(self, error: Exception) -> bool:
        if isinstance(error, ResponseError) and "think" in str(error).lower():
            _thinking_support[self.model] = False
            return True
        return False


# vLLM models whose server rejected JSON mode (response_format); their JSON tasks are asked without it
_no_json_mode: set = set()


def _vllm_settings(think: bool) -> dict:
    """Fields of a VllmChatModel that thinks or replies directly. Qwen3's chat template switches the thinking
    (enable_thinking); top_k is no OpenAI parameter and goes in the request body."""
    sampling = THINKING_SAMPLING if think else DIRECT_SAMPLING
    body = {"chat_template_kwargs": {"enable_thinking": think}}
    if sampling["top_k"]:
        body["top_k"] = sampling["top_k"]
    return {
        "enable_thinking": think,
        "max_tokens": OLLAMA_THINK_NUM_PREDICT if think else OLLAMA_NUM_PREDICT,
        "temperature": sampling["temperature"],
        "top_p": sampling["top_p"],
        "seed": OLLAMA_SEED if think and OLLAMA_SEED >= 0 else None,
        "extra_body": body,
    }


class VllmChatModel(_ThinkingFallback, ChatOpenAI):
    """ChatOpenAI for a vLLM server (OpenAI-compatible API) serving a qwen3 model.

    Thinking is switched per call by Qwen3's chat template (enable_thinking). Start the server with
    `--reasoning-parser qwen3` so the thinking comes apart from the reply; without it the thinking block is removed
    from the reply here. A thinking call that reaches its token limit, or does not fit the server's context window
    (--max-model-len), is answered again without thinking (see _ThinkingFallback). A server that rejects JSON mode
    is asked without it.
    """

    enable_thinking: bool = False

    def _model_label(self) -> str:
        return self.model_name

    def _thinks(self, kwargs: dict) -> bool:
        return self.enable_thinking

    def _without_thinking(self) -> "VllmChatModel":
        return self.model_copy(update=_vllm_settings(False))

    def _limit_reached(self, generation) -> bool:
        return (generation.generation_info or {}).get("finish_reason") == "length"

    def _failed_by_thinking(self, error: Exception) -> bool:
        # The prompt plus the thinking budget (max_tokens) is longer than the server's context window
        return isinstance(error, openai.BadRequestError) and "context length" in str(error).lower()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        if "response_format" in kwargs and self.model_name in _no_json_mode:
            kwargs.pop("response_format")
        try:
            return super()._generate(messages, stop, run_manager, **kwargs)
        except openai.BadRequestError as e:
            if "response_format" not in kwargs or not re.search(r"response_format|guided|structured|grammar", str(e)):
                raise
            logger.warning(f"[LLM] The vLLM server rejected JSON mode ({e}); asking without it from now on.")
            _no_json_mode.add(self.model_name)
            kwargs.pop("response_format")
            return super()._generate(messages, stop, run_manager, **kwargs)


def llm_model_name() -> str:
    """Model that writes the answers: VLLM_MODEL with LLM_BACKEND=vllm, else OLLAMA_MODEL."""
    return VLLM_MODEL if LLM_BACKEND == "vllm" else OLLAMA_MODEL


def router_model_name() -> str:
    """Model that routes questions to agents (OLLAMA_ROUTER_MODEL, else the answer model; vLLM: the answer model)."""
    return llm_model_name() if LLM_BACKEND == "vllm" else OLLAMA_ROUTER_MODEL or OLLAMA_MODEL


def grader_model_name() -> str:
    """Model that checks answers against the documents (OLLAMA_GRADER_MODEL, else the answer model; vLLM: the
    answer model)."""
    return llm_model_name() if LLM_BACKEND == "vllm" else OLLAMA_GRADER_MODEL or OLLAMA_MODEL


def configured_models() -> list:
    """Distinct models in use: answers, routing, and answer grading."""
    return list(dict.fromkeys([llm_model_name(), router_model_name(), grader_model_name()]))


def create_chat_model(model: Optional[str] = None):
    """Return a LangChain chat model backed by the configured server (LLM_BACKEND); it replies without thinking
    (for_task() gives the thinking variant for a task).

    model: model name; None uses the answer model (OLLAMA_MODEL, or VLLM_MODEL with LLM_BACKEND=vllm).
    The returned object implements standard LangChain ChatModel interfaces:
        - chat_model.invoke(messages)  -> Batch response
        - chat_model.stream(messages)  -> Token stream
        - chat_model.bind_tools(tools) -> Tool binding
    No connection is made here; use check_llm() to verify the server and model.
    """
    _warn_about_ignored_settings()
    model = model or llm_model_name()
    thinking = ", ".join(sorted(OLLAMA_THINK_TASKS)) or "none"
    if LLM_BACKEND == "vllm":
        logger.info(f"Using vLLM at {VLLM_BASE_URL} with model '{model}' (thinking for: {thinking}).")
        return VllmChatModel(
            base_url=VLLM_BASE_URL,
            api_key=VLLM_API_KEY,
            model=model,
            # vLLM serves the Chat Completions API only
            use_responses_api=False,
            **_vllm_settings(False),
        )
    logger.info(
        f"Using Ollama at {OLLAMA_BASE_URL} with model '{model}' (num_ctx={OLLAMA_NUM_CTX}, thinking for: {thinking})."
    )
    return OllamaChatModel(
        base_url=OLLAMA_BASE_URL,
        model=model,
        # False, not None: qwen3 thinks by default and would write its thinking into the reply
        reasoning=False,
        num_predict=OLLAMA_NUM_PREDICT,
        num_ctx=OLLAMA_NUM_CTX,
        # None: Ollama decides how many layers fit on the GPU
        num_gpu=OLLAMA_NUM_GPU if OLLAMA_NUM_GPU >= 0 else None,
        **DIRECT_SAMPLING,
    )


def thinks_for(task: str) -> bool:
    """Whether calls of this task think (OLLAMA_THINK_TASKS), for models that can."""
    return "all" in OLLAMA_THINK_TASKS or task in OLLAMA_THINK_TASKS


def for_task(chat_model, task: str):
    """The model for one task: thinking or not by OLLAMA_THINK_TASKS (see thinks_for).

    Ollama models that cannot think (supports_thinking) reply directly; a vLLM model is taken to be a qwen3 model
    (other chat templates ignore the switch). Other chat models (test doubles) are returned as is.
    """
    if isinstance(chat_model, VllmChatModel):
        think = thinks_for(task)
        return (
            chat_model if chat_model.enable_thinking == think else chat_model.model_copy(update=_vllm_settings(think))
        )
    if not isinstance(chat_model, OllamaChatModel):
        return chat_model
    think = thinks_for(task) and supports_thinking(chat_model.model)
    if bool(chat_model.reasoning) == think:
        return chat_model
    if not think:
        return chat_model._without_thinking()
    seed = {"seed": OLLAMA_SEED} if OLLAMA_SEED >= 0 else {}
    return chat_model.model_copy(
        update={"reasoning": True, "num_predict": OLLAMA_THINK_NUM_PREDICT, **THINKING_SAMPLING, **seed}
    )


def is_thinking(chat_model) -> bool:
    """Whether calls of this model think (a model from for_task for a thinking task)."""
    if isinstance(chat_model, VllmChatModel):
        return chat_model.enable_thinking
    return getattr(chat_model, "reasoning", None) is True


def json_mode(chat_model):
    """The same model constrained to valid JSON output (Ollama's format="json", vLLM's response_format); other
    models are returned as is.

    Small models occasionally break the JSON of a routing decision (a missing comma, a raw line break in a
    string); JSON mode rules that out at decoding time.
    """
    if isinstance(chat_model, VllmChatModel):
        return chat_model.bind(response_format={"type": "json_object"})
    return chat_model.bind(format="json") if isinstance(chat_model, ChatOllama) else chat_model


def check_llm(timeout: float = 3.0) -> Optional[str]:
    """Return None if the LLM server (LLM_BACKEND) is reachable and serves the configured models, otherwise a
    readable problem."""
    return check_vllm(timeout) if LLM_BACKEND == "vllm" else check_ollama(timeout)


def check_ollama(timeout: float = 3.0) -> Optional[str]:
    """Return None if the Ollama server is reachable and every configured model is pulled, otherwise a readable problem."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            models = json.load(response).get("models", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        return (
            f"Ollama server is not reachable at {OLLAMA_BASE_URL} ({e}). "
            "Start Ollama, or set OLLAMA_BASE_URL to the right address."
        )

    available = {_with_tag(m.get("name") or m.get("model", "")) for m in models}
    missing = [model for model in configured_models() if _with_tag(model) not in available]
    if missing:
        pulls = "; ".join(f"ollama pull {model}" for model in missing)
        return f"Ollama model(s) {', '.join(repr(m) for m in missing)} not pulled. Run: {pulls}"
    return None


def check_vllm(timeout: float = 3.0) -> Optional[str]:
    """Return None if the vLLM server is reachable and serves VLLM_MODEL, otherwise a readable problem."""
    request = urllib.request.Request(
        f"{VLLM_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {VLLM_API_KEY}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            served = [m.get("id", "") for m in json.load(response).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError) as e:
        return (
            f"vLLM server is not reachable at {VLLM_BASE_URL} ({e}). Start it "
            f"(vllm serve {VLLM_MODEL} --reasoning-parser qwen3), or set VLLM_BASE_URL to the right address."
        )
    if VLLM_MODEL not in served:
        return (
            f"The vLLM server at {VLLM_BASE_URL} serves {', '.join(repr(m) for m in served) or 'no model'}, not "
            f"'{VLLM_MODEL}'. Start it with: vllm serve {VLLM_MODEL}, or set VLLM_MODEL to the served model."
        )
    return None


_status_lock = threading.Lock()
_status = {"checked_at": None, "problem": None}


def llm_problem(max_age: float = LLM_STATUS_CACHE_SECONDS) -> Optional[str]:
    """check_llm(), reused for max_age seconds. Questions call this before running: the server answers in
    milliseconds, but an unreachable remote host takes the whole timeout, which concurrent questions then share."""
    with _status_lock:
        now = time.monotonic()
        if _status["checked_at"] is None or now - _status["checked_at"] >= max_age:
            _status["problem"] = check_llm(timeout=2.0)
            _status["checked_at"] = time.monotonic()
            if _status["problem"]:
                logger.error(f"[LLM] {_status['problem']}")
        return _status["problem"]


def _with_tag(name: str) -> str:
    """Ollama treats 'llama3.1' and 'llama3.1:latest' as the same model."""
    return name if ":" in name else f"{name}:latest"


def _warn_about_ignored_settings() -> None:
    legacy = [name for name in REMOVED_SETTINGS if os.getenv(name)]
    backend = os.getenv("LLM_BACKEND", "").lower()
    if backend and backend not in BACKENDS:
        legacy.insert(0, "LLM_BACKEND")
    if legacy:
        logger.warning(
            f"Ignoring {', '.join(legacy)}: the in-process HuggingFace LLM backend was removed and the LLM runs on "
            f"Ollama (OLLAMA_MODEL={OLLAMA_MODEL}) or vLLM (LLM_BACKEND=vllm). Remove these settings from your .env."
        )
    if LLM_BACKEND == "vllm" and (OLLAMA_ROUTER_MODEL or OLLAMA_GRADER_MODEL):
        logger.warning(
            f"Ignoring OLLAMA_ROUTER_MODEL / OLLAMA_GRADER_MODEL: with vLLM, '{VLLM_MODEL}' routes and checks too."
        )
