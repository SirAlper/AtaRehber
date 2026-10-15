"""Chat model factory. The LLM is served by Ollama; no model weights are loaded in this process.

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

from langchain_ollama import ChatOllama
from ollama import ResponseError

from src.core.config import (
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
)
from src.core.logger import get_logger

logger = get_logger("LLM")

# Settings of the removed in-process HuggingFace backend; warn if a .env still sets them
REMOVED_SETTINGS = ("LLM_MODEL_ID", "LLM_MODEL_DIR")

# Sampling of thinking calls as Qwen recommends for qwen3: greedy decoding (temperature 0) makes the thinking
# repeat itself endlessly. Calls without thinking stay greedy, so their replies are repeatable.
THINKING_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
DIRECT_SAMPLING = {"temperature": 0.0, "top_p": None, "top_k": None}

# Thinking left in the reply itself (Ollama versions without the "think" setting): "<think>...</think>", or only
# its end when the template opened the block
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


class OllamaChatModel(ChatOllama):
    """ChatOllama that answers a thinking call again without thinking when it cannot think or ran out of tokens.

    A thinking call that reaches its token limit (OLLAMA_THINK_NUM_PREDICT) has used it up thinking, or cut the
    answer off; the same messages are then sent without thinking. A model Ollama says cannot think is asked without
    thinking from then on. A thinking block left in the reply is removed.
    """

    def _without_thinking(self) -> "OllamaChatModel":
        return self.model_copy(update={"reasoning": False, "num_predict": OLLAMA_NUM_PREDICT, **DIRECT_SAMPLING})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        thinking = kwargs.get("reasoning", self.reasoning) is True
        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
        except ResponseError as e:
            if not thinking or "think" not in str(e).lower():
                raise
            logger.warning(f"[LLM] '{self.model}' cannot think ({e}); asking it without thinking.")
            _thinking_support[self.model] = False
            kwargs.pop("reasoning", None)
            return self._without_thinking()._generate(messages, stop, run_manager, **kwargs)

        generation = result.generations[0]
        if thinking and (generation.generation_info or {}).get("done_reason") == "length":
            thought = len(str(generation.message.additional_kwargs.get("reasoning_content") or ""))
            logger.warning(
                f"[LLM] '{self.model}' reached the token limit ({self.num_predict}) after {thought} characters of "
                "thinking; answering again without thinking."
            )
            kwargs.pop("reasoning", None)
            return self._without_thinking()._generate(messages, stop, run_manager, **kwargs)
        if isinstance(generation.message.content, str) and "think>" in generation.message.content:
            generation.message.content = strip_thinking(generation.message.content)
            generation.text = generation.message.content
        return result


def router_model_name() -> str:
    """Model that routes questions to agents (OLLAMA_ROUTER_MODEL, else OLLAMA_MODEL)."""
    return OLLAMA_ROUTER_MODEL or OLLAMA_MODEL


def grader_model_name() -> str:
    """Model that checks answers against the documents (OLLAMA_GRADER_MODEL, else OLLAMA_MODEL)."""
    return OLLAMA_GRADER_MODEL or OLLAMA_MODEL


def configured_models() -> list:
    """Distinct Ollama models in use: answers (OLLAMA_MODEL), routing, and answer grading."""
    return list(dict.fromkeys([OLLAMA_MODEL, router_model_name(), grader_model_name()]))


def create_chat_model(model: Optional[str] = None) -> ChatOllama:
    """Return a LangChain chat model backed by the configured Ollama server; it replies without thinking
    (for_task() gives the thinking variant for a task).

    model: Ollama model name; None uses OLLAMA_MODEL.
    The returned object implements standard LangChain ChatModel interfaces:
        - chat_model.invoke(messages)  -> Batch response
        - chat_model.stream(messages)  -> Token stream
        - chat_model.bind_tools(tools) -> Tool binding
    No connection is made here; use check_ollama() to verify the server and model.
    """
    _warn_about_removed_settings()
    model = model or OLLAMA_MODEL
    logger.info(
        f"Using Ollama at {OLLAMA_BASE_URL} with model '{model}' (num_ctx={OLLAMA_NUM_CTX}, "
        f"thinking for: {', '.join(sorted(OLLAMA_THINK_TASKS)) or 'none'})."
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

    Models that cannot think (supports_thinking) reply directly; other chat models (test doubles) are returned
    as is.
    """
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
    return getattr(chat_model, "reasoning", None) is True


def json_mode(chat_model):
    """The same model constrained to valid JSON output (Ollama's format="json"); other models are returned as is.

    Small models occasionally break the JSON of a routing decision (a missing comma, a raw line break in a
    string); JSON mode rules that out at decoding time.
    """
    return chat_model.bind(format="json") if isinstance(chat_model, ChatOllama) else chat_model


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


_status_lock = threading.Lock()
_status = {"checked_at": None, "problem": None}


def llm_problem(max_age: float = LLM_STATUS_CACHE_SECONDS) -> Optional[str]:
    """check_ollama(), reused for max_age seconds. Questions call this before running: Ollama answers in
    milliseconds, but an unreachable remote host takes the whole timeout, which concurrent questions then share."""
    with _status_lock:
        now = time.monotonic()
        if _status["checked_at"] is None or now - _status["checked_at"] >= max_age:
            _status["problem"] = check_ollama(timeout=2.0)
            _status["checked_at"] = time.monotonic()
            if _status["problem"]:
                logger.error(f"[LLM] {_status['problem']}")
        return _status["problem"]


def _with_tag(name: str) -> str:
    """Ollama treats 'llama3.1' and 'llama3.1:latest' as the same model."""
    return name if ":" in name else f"{name}:latest"


def _warn_about_removed_settings() -> None:
    legacy = [name for name in REMOVED_SETTINGS if os.getenv(name)]
    backend = os.getenv("LLM_BACKEND", "").lower()
    if backend and backend != "ollama":
        legacy.insert(0, "LLM_BACKEND")
    if legacy:
        logger.warning(
            f"Ignoring {', '.join(legacy)}: the in-process HuggingFace LLM backend was removed and the LLM always "
            f"runs on Ollama (OLLAMA_MODEL={OLLAMA_MODEL}). Remove these settings from your .env."
        )
