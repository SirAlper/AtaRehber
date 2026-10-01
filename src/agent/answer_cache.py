"""Cache of verified doc_agent answers to first questions (no conversation yet).

During registration weeks many people ask the same questions. An answer is reused only for the same question
(ignoring case, spacing, and final punctuation), the same document access, and the same index version: any
upload, deletion, or access change increments RAGEngine.index_version, so answers built on old documents are
never reused. Follow-up questions depend on the conversation and are not cached.
"""

import copy
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Hashable, Optional

from src.core import config


def normalize_question(question: str) -> str:
    text = str(question).replace("İ", "i").replace("I", "ı").casefold()
    return re.sub(r"\s+", " ", text).strip().rstrip("?.!…").strip()


class AnswerCache:
    """Thread-safe LRU cache with a time limit; size and time limit come from the settings at each call."""

    def __init__(self):
        self._entries: "OrderedDict[Hashable, tuple]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(question: str, scope: Optional[list], index_version: Any, user_note: str = "") -> Hashable:
        # user_note: answers given for a unit, program, or level are only reused for the same one
        return (normalize_question(question), tuple(scope) if scope is not None else None, index_version, user_note)

    def get(self, key: Hashable) -> Optional[Dict[str, Any]]:
        if config.ANSWER_CACHE_SIZE <= 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.time() - stored_at > config.ANSWER_CACHE_MINUTES * 60:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(value)

    def put(self, key: Hashable, value: Dict[str, Any]) -> None:
        if config.ANSWER_CACHE_SIZE <= 0:
            return
        with self._lock:
            self._entries[key] = (time.time(), copy.deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > config.ANSWER_CACHE_SIZE:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


answer_cache = AnswerCache()
