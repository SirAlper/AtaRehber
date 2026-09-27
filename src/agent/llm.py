"""Chat model factory. The LLM is served by Ollama; no model weights are loaded in this process."""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from langchain_ollama import ChatOllama

from src.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_NUM_CTX
from src.core.logger import get_logger

logger = get_logger("LLM")

# Settings of the removed in-process HuggingFace backend; warn if a .env still sets them
REMOVED_SETTINGS = ("LLM_MODEL_ID", "LLM_MODEL_DIR")


def create_chat_model() -> ChatOllama:
    """Return a LangChain chat model backed by the configured Ollama server.

    The returned object implements standard LangChain ChatModel interfaces:
        - chat_model.invoke(messages)  -> Batch response
        - chat_model.stream(messages)  -> Token stream
        - chat_model.bind_tools(tools) -> Tool binding
    No connection is made here; use check_ollama() to verify the server and model.
    """
    _warn_about_removed_settings()
    logger.info(f"Using Ollama at {OLLAMA_BASE_URL} with model '{OLLAMA_MODEL}' (num_ctx={OLLAMA_NUM_CTX}).")
    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_MODEL,
        temperature=0.0,
        num_predict=512,
        num_ctx=OLLAMA_NUM_CTX,
    )


def check_ollama(timeout: float = 3.0) -> Optional[str]:
    """Return None if the Ollama server is reachable and OLLAMA_MODEL is pulled, otherwise a readable problem."""
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
    if _with_tag(OLLAMA_MODEL) not in available:
        return f"Ollama model '{OLLAMA_MODEL}' is not pulled. Run: ollama pull {OLLAMA_MODEL}"
    return None


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
