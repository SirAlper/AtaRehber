"""Conversation session retention for the multi-agent LangGraph SQLite checkpointer."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.core.config import MULTI_AGENT_CONVERSATIONS_DB
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Sessions")


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def cleanup_expired_sessions(max_age_days: int = 30, db_path: str = MULTI_AGENT_CONVERSATIONS_DB) -> int:
    """Delete conversation threads whose latest checkpoint is older than max_age_days.

    Returns the number of deleted threads. Threads with an unreadable timestamp are kept.
    """
    if not os.path.exists(db_path):
        return 0

    from langgraph.checkpoint.sqlite import SqliteSaver

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
    deleted = 0
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        thread_ids = [row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()]
        for thread_id in thread_ids:
            latest = saver.get_tuple({"configurable": {"thread_id": thread_id}})
            if latest is None:
                continue
            ts = _parse_ts(latest.checkpoint.get("ts", ""))
            if ts is None or ts >= cutoff:
                continue
            saver.delete_thread(thread_id)
            deleted += 1
    finally:
        conn.close()

    logger.info(f"[Session Cleanup] Removed {deleted} conversation thread(s) older than {max_age_days} days.")
    return deleted
