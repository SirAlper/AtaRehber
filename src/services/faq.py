"""Staff answers to unanswered questions (FAQ): the loop that lets the assistant learn from its gaps.

Questions the documents do not answer, and answers users rated down, are listed for review. Staff answer them
here; each answer is stored in FAQ_FILE (data directory, so full backups include it) and indexed as its own chunk
under the source FAQ_SOURCE, with the same access groups as documents. The next time anyone asks, doc_agent finds
the staff answer and cites it like a document. Users who asked the question see the answer in the web UI.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.agent.answer_cache import normalize_question
from src.auth.document_access import access_metadata, normalize_groups
from src.core.config import FAQ_FILE
from src.core.logger import get_logger

logger = get_logger("FAQ")

# Vector-store "source" of the FAQ chunks; shown as the document name of a cited staff answer
FAQ_SOURCE = "SSS (personel cevapları)"
MAX_QUESTION_LENGTH = 500
MAX_ANSWER_LENGTH = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FaqStore:
    """Thread-safe JSON store of FAQ entries.

    Entry: {"id", "question", "answer", "groups", "author", "created_at", "updated_at",
            "asked": [{"username", "question"}], "seen_by": [usernames]}
    """

    def __init__(self, path: str = FAQ_FILE):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError) as e:
            logger.error(f"Could not read {self.path}: {e}")
            return []

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temp = f"{self.path}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def add(
        self,
        question: str,
        answer: str,
        author: str,
        groups: Optional[Iterable[str]] = None,
        asked: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Store a staff answer; `asked` names the users (and their wording) who will be shown the answer."""
        question, answer = _clean(question, MAX_QUESTION_LENGTH), _clean(answer, MAX_ANSWER_LENGTH, keep_lines=True)
        if not question or not answer:
            raise ValueError("Question and answer must not be empty.")
        entry = {
            "id": uuid.uuid4().hex[:12],
            "question": question,
            "answer": answer,
            "groups": normalize_groups(list(groups or [])),
            "author": author,
            "created_at": _now(),
            "updated_at": _now(),
            "asked": _unique_asked(asked or []),
            "seen_by": [],
        }
        with self._lock:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        return entry

    def update(
        self, entry_id: str, question: str, answer: str, groups: Optional[Iterable[str]] = None
    ) -> Optional[Dict[str, Any]]:
        question, answer = _clean(question, MAX_QUESTION_LENGTH), _clean(answer, MAX_ANSWER_LENGTH, keep_lines=True)
        if not question or not answer:
            raise ValueError("Question and answer must not be empty.")
        groups = normalize_groups(list(groups or []))
        with self._lock:
            entries = self._load()
            for entry in entries:
                if entry["id"] == entry_id:
                    changed = entry["answer"] != answer
                    entry.update(question=question, answer=answer, groups=groups, updated_at=_now())
                    if changed:
                        # A corrected answer is shown again to the users who asked
                        entry["seen_by"] = []
                    self._save(entries)
                    return entry
        return None

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            entries = self._load()
            kept = [e for e in entries if e["id"] != entry_id]
            if len(kept) == len(entries):
                return False
            self._save(kept)
            return True

    def answered(self) -> set:
        """(username, normalized question) of every question staff have answered (to leave out of the review list)."""
        return {
            (asked["username"], normalize_question(asked["question"]))
            for entry in self.list()
            for asked in entry.get("asked", [])
        }

    def unseen_for(self, username: str) -> List[Dict[str, Any]]:
        """Answers to this user's questions they have not marked as seen."""
        return [
            {
                "id": e["id"],
                "question": next(a["question"] for a in e["asked"] if a["username"] == username),
                "answer": e["answer"],
                "updated_at": e.get("updated_at") or e["created_at"],
            }
            for e in self.list()
            if any(a["username"] == username for a in e.get("asked", [])) and username not in e.get("seen_by", [])
        ]

    def mark_seen(self, username: str, entry_ids: Iterable[str]) -> int:
        wanted = set(entry_ids)
        count = 0
        with self._lock:
            entries = self._load()
            for entry in entries:
                if entry["id"] in wanted and username not in entry.get("seen_by", []):
                    entry.setdefault("seen_by", []).append(username)
                    count += 1
            if count:
                self._save(entries)
        return count


def _clean(text: str, limit: int, keep_lines: bool = False) -> str:
    text = str(text or "").strip()
    if not keep_lines:
        text = " ".join(text.split())
    return text[:limit]


def _unique_asked(asked: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen, result = set(), []
    for item in asked:
        username, question = str(item.get("username") or ""), _clean(item.get("question", ""), MAX_QUESTION_LENGTH)
        if not username or not question or username.startswith("guest-"):
            # Guests have no account to show the answer to later
            continue
        key = (username, normalize_question(question))
        if key not in seen:
            seen.add(key)
            result.append({"username": username, "question": question})
    return result


def faq_chunks(entries: List[Dict[str, Any]]):
    """(documents, ids, metadatas) for the vector store: one chunk per answer, with its access groups."""
    documents, ids, metadatas = [], [], []
    for index, entry in enumerate(entries):
        documents.append(f"[{FAQ_SOURCE} | {entry['question']}]\n{entry['question']}\n{entry['answer']}")
        ids.append(f"faq_{entry['id']}")
        metadata = {
            "source": FAQ_SOURCE,
            "chunk_index": index,
            "document_title": FAQ_SOURCE,
            "article": entry["question"][:120],
        }
        if entry.get("groups"):
            metadata.update(access_metadata(entry["groups"]))
        metadatas.append(metadata)
    return documents, ids, metadatas


def reindex_faq(engine, store: "FaqStore") -> int:
    """Replace the FAQ chunks in the vector store with the stored answers; returns the chunk count."""
    entries = store.list()
    engine.delete_document(FAQ_SOURCE)
    if entries:
        engine.add_documents(*faq_chunks(entries))
    logger.info(f"[FAQ] {len(entries)} staff answer(s) indexed.")
    return len(entries)


faq_store = FaqStore()
