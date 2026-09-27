"""Service requests ("talep"): records users open from the chat or the API, e.g. an IT fault or a room booking.

Requests are stored in a local SQLite database (REQUESTS_DB, part of full backups). Staff (admin/editor) work
them off by changing their status; the requester can follow them and cancel open ones. The responsible unit can
be notified by e-mail through the organization's own mail server (see src/services/notifier.py).
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.config import REQUEST_CATEGORIES, REQUESTS_DB
from src.core.logger import get_logger

logger = get_logger("ServiceRequests")

STATUSES = ("open", "in_progress", "resolved", "rejected", "cancelled")
OPEN_STATUSES = ("open", "in_progress")
CLOSED_STATUSES = ("resolved", "rejected", "cancelled")
FALLBACK_CATEGORY = "other"


def normalize_category(category: Optional[str]) -> str:
    """Map a free-form category onto REQUEST_CATEGORIES ('other', or the first category, when unknown)."""
    value = (category or "").strip().lower().replace(" ", "_").replace("-", "_")
    if value in REQUEST_CATEGORIES:
        return value
    if FALLBACK_CATEGORY in REQUEST_CATEGORIES:
        return FALLBACK_CATEGORY
    return REQUEST_CATEGORIES[0] if REQUEST_CATEGORIES else FALLBACK_CATEGORY


class ServiceRequestStore:
    """Thread-safe SQLite store of service requests."""

    def __init__(self, db_path: str = REQUESTS_DB):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution_note TEXT NOT NULL DEFAULT '',
                    updated_by TEXT,
                    notified INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_user ON service_requests(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON service_requests(status)")
        self._initialized = True

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        record = dict(row)
        record["notified"] = bool(record.get("notified"))
        return record

    def create(self, username: str, category: str, title: str, description: str = "") -> Dict[str, Any]:
        title = " ".join(title.split())[:200]
        if len(title) < 3:
            raise ValueError("Request title is too short.")
        now = self._now()
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO service_requests (created_at, updated_at, username, category, title, description) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (now, now, username, normalize_category(category), title, description.strip()[:4000]),
                )
                row = conn.execute("SELECT * FROM service_requests WHERE id = ?", (cursor.lastrowid,)).fetchone()
        record = self._to_dict(row)
        logger.info(f"Service request #{record['id']} [{record['category']}] opened by '{username}'.")
        return record

    def get(self, request_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM service_requests WHERE id = ?", (request_id,)).fetchone()
        return self._to_dict(row)

    def list(
        self, username: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Newest first; username/status filter when given."""
        clauses, params = [], []
        if username is not None:
            clauses.append("username = ?")
            params.append(username)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM service_requests {where} ORDER BY id DESC LIMIT ?", params
                ).fetchall()
        return [self._to_dict(row) for row in rows]

    def update_status(
        self, request_id: int, status: str, updated_by: str, resolution_note: str = ""
    ) -> Optional[Dict[str, Any]]:
        if status not in STATUSES:
            raise ValueError(f"Unknown status '{status}'.")
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE service_requests SET status = ?, resolution_note = ?, updated_by = ?, updated_at = ? "
                    "WHERE id = ?",
                    (status, resolution_note.strip()[:2000], updated_by, self._now(), request_id),
                )
                if cursor.rowcount == 0:
                    return None
                row = conn.execute("SELECT * FROM service_requests WHERE id = ?", (request_id,)).fetchone()
        return self._to_dict(row)

    def mark_notified(self, request_id: int) -> None:
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                conn.execute("UPDATE service_requests SET notified = 1 WHERE id = ?", (request_id,))

    def purge_closed_older_than_days(self, days: int) -> int:
        """Delete resolved, rejected, and cancelled requests last updated more than `days` days ago."""
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        placeholders = ", ".join("?" for _ in CLOSED_STATUSES)
        with self._lock:
            self._ensure_schema()
            with self._connect() as conn:
                cursor = conn.execute(
                    f"DELETE FROM service_requests WHERE status IN ({placeholders}) AND updated_at < ?",
                    (*CLOSED_STATUSES, cutoff),
                )
                return cursor.rowcount


_store: Optional[ServiceRequestStore] = None
_store_lock = threading.Lock()


def get_request_store() -> ServiceRequestStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ServiceRequestStore()
        return _store
