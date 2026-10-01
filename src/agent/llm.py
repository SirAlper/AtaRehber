"""Chat model factory. The LLM is served by Ollama; no model weights are loaded in this process."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from langchain_ollama import ChatOllama

from src.core.config import (
    LLM_STATUS_CACHE_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_GRADER_MODEL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_GPU,
    OLLAMA_ROUTER_MODEL,
)
from src.core.logger import get_logger

logger = get_logger("LLM")

# Settings of the removed in-process HuggingFace backend; warn if a .env still sets them
REMOVED_SETTINGS = ("LLM_MODEL_ID", "LLM_MODEL_DIR")


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
    """Return a LangChain chat model backed by the configured Ollama server.

    model: Ollama model name; None uses OLLAMA_MODEL.
    The returned object implements standard LangChain ChatModel interfaces:
        - chat_model.invoke(messages)  -> Batch response
        - chat_model.stream(messages)  -> Token stream
        - chat_model.bind_tools(tools) -> Tool binding
    No connection is made here; use check_ollama() to verify the server and model.
    """
    _warn_about_removed_settings()
    model = model or OLLAMA_MODEL
    logger.info(f"Using Ollama at {OLLAMA_BASE_URL} with model '{model}' (num_ctx={OLLAMA_NUM_CTX}).")
    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=model,
        temperature=0.0,
        num_predict=512,
        num_ctx=OLLAMA_NUM_CTX,
        # None: Ollama decides how many layers fit on the GPU
        num_gpu=OLLAMA_NUM_GPU if OLLAMA_NUM_GPU >= 0 else None,
    )


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
