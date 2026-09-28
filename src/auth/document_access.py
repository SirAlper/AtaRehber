"""Document-level access control: which user groups may search a document.

Documents are visible to everyone unless they are restricted to one or more user groups. The mapping lives in
DOCUMENT_ACCESS_FILE (data directory, so it is part of full backups) and is mirrored into the metadata of the
document's chunks so that searches can filter in the vector store: chunks of a restricted document carry
acl_public=False and acl_<group>=True. Chunks without acl_public (indexed before access control existed, or
synced from database tables) are public.

Admins and editors manage documents and see all of them; viewers only see public documents and documents
restricted to one of their groups. Guests (visitors without an account) only see documents shared with
GUEST_DOCUMENT_GROUP; those documents are meant for the public, so every account sees them as well.
"""

import json
import os
import re
import threading
from typing import Dict, Iterable, List, Optional, Union

from src.core.config import DOCUMENT_ACCESS_FILE, GUEST_DOCUMENT_GROUP
from src.core.logger import get_logger

logger = get_logger("DocumentAccess")

GROUP_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
# Roles that manage documents and are never filtered
DOCUMENT_MANAGER_ROLES = ("admin", "editor")
PUBLIC_KEY = "acl_public"
GUEST_ROLE = "guest"
# First entry of a search scope that leaves out public documents: only the groups after it are searched (guests)
ONLY_GROUPS = "*only"


def normalize_groups(groups: Union[None, str, Iterable[str]]) -> List[str]:
    """Clean a group list ("akademik, idari" or ["Akademik"]) into sorted lowercase names; raises ValueError."""
    if groups is None:
        return []
    items = groups.split(",") if isinstance(groups, str) else list(groups)
    cleaned = sorted({str(g).strip().lower() for g in items if str(g).strip()})
    invalid = [g for g in cleaned if not GROUP_PATTERN.match(g)]
    if invalid:
        raise ValueError(
            f"Invalid group name(s): {', '.join(invalid)}. Use 1-32 lowercase letters, digits, or underscores."
        )
    return cleaned


def group_key(group: str) -> str:
    return f"acl_{group}"


def access_metadata(groups: List[str], previous_groups: Iterable[str] = ()) -> Dict[str, bool]:
    """Chunk metadata for a document visible to `groups` (empty: everyone).

    Metadata updates are merged in the vector store, so groups that lost access are set to False explicitly.
    """
    metadata: Dict[str, bool] = {PUBLIC_KEY: not groups}
    for group in set(previous_groups) - set(groups):
        metadata[group_key(group)] = False
    for group in groups:
        metadata[group_key(group)] = True
    return metadata


def search_filter(groups: List[str]) -> dict:
    """Vector store `where` filter for a scope from allowed_groups_for(): public chunks plus chunks shared with a
    group, or only the chunks shared with the groups after ONLY_GROUPS."""
    if groups and groups[0] == ONLY_GROUPS:
        shared = [{group_key(g): True} for g in groups[1:]]
        if not shared:
            # No group: nothing may be searched ("acl_" is never set, group names are not empty)
            return {group_key(""): True}
        return shared[0] if len(shared) == 1 else {"$or": shared}
    # $ne also matches chunks without the key, i.e. everything indexed as public
    public = {PUBLIC_KEY: {"$ne": False}}
    if not groups:
        return public
    return {"$or": [public] + [{group_key(g): True} for g in groups]}


def allowed_groups_for(role: Optional[str], groups: Optional[Iterable[str]]) -> Optional[List[str]]:
    """Search scope of a user: None means no filtering (document managers); a list means public documents plus
    the documents of these groups; a list starting with ONLY_GROUPS means only the documents of these groups."""
    if role in DOCUMENT_MANAGER_ROLES:
        return None
    if role == GUEST_ROLE:
        return [ONLY_GROUPS, GUEST_DOCUMENT_GROUP]
    # Documents shared with visitors are public information: every account sees them
    return sorted(set(groups or []) | {GUEST_DOCUMENT_GROUP})


class DocumentAccessStore:
    """Thread-safe JSON mapping {filename: [groups]} of restricted documents."""

    def __init__(self, file_path: str = DOCUMENT_ACCESS_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, List[str]]:
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, encoding="utf-8") as f:
                data = json.load(f)
            return {name: list(groups) for name, groups in data.items() if groups}
        except Exception as e:
            # Never guess: treating an unreadable file as "no restrictions" would expose restricted documents
            logger.error(f"Cannot read document access file {self.file_path}: {e}")
            raise

    def _save(self, data: Dict[str, List[str]]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        temp_file = f"{self.file_path}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temp_file, self.file_path)

    def get(self, filename: str) -> List[str]:
        with self._lock:
            return list(self._load().get(filename, []))

    def all(self) -> Dict[str, List[str]]:
        with self._lock:
            return self._load()

    def set(self, filename: str, groups: List[str]) -> List[str]:
        """Store the groups of a document (empty list: visible to everyone); returns the previous groups."""
        with self._lock:
            data = self._load()
            previous = data.get(filename, [])
            if groups:
                data[filename] = list(groups)
            else:
                data.pop(filename, None)
            self._save(data)
            return previous

    def remove(self, filename: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(filename, None) is not None:
                self._save(data)

    def can_access(self, filename: str, role: Optional[str], user_groups: Optional[Iterable[str]]) -> bool:
        allowed = allowed_groups_for(role, user_groups)
        if allowed is None:
            return True
        groups = self.get(filename)
        if allowed and allowed[0] == ONLY_GROUPS:
            return bool(set(groups) & set(allowed[1:]))
        return not groups or bool(set(groups) & set(allowed))


document_access_store = DocumentAccessStore()
