"""Scheduled maintenance: retention policy and automatic backups.

Runs once at startup and then hourly inside the API process. Every task is off by default and enabled
through settings (AUDIT_RETENTION_DAYS, SESSION_RETENTION_DAYS, REQUEST_RETENTION_DAYS, BACKUP_INTERVAL_HOURS).
The backup schedule is derived from the newest full backup on disk, so restarts do not reset it.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.agent.multi_agent.sessions import cleanup_expired_sessions
from src.api.state import index_write_lock
from src.core import config
from src.services import backups
from src.core.audit import audit_logger
from src.core.logger import get_logger

logger = get_logger("API.Maintenance")

MAINTENANCE_INTERVAL_SECONDS = 3600


def backup_due(now: datetime) -> bool:
    if config.BACKUP_INTERVAL_HOURS <= 0:
        return False
    latest = backups.latest_full_backup_time()
    return latest is None or now - latest >= timedelta(hours=config.BACKUP_INTERVAL_HOURS)


def run_maintenance_once() -> Dict[str, Any]:
    """Apply the retention policy and take a backup if one is due. Returns what was done."""
    now = datetime.now(timezone.utc)
    results: Dict[str, Any] = {}

    if config.AUDIT_RETENTION_DAYS > 0:
        results["audit_entries_deleted"] = audit_logger.purge_older_than_days(config.AUDIT_RETENTION_DAYS)
    if config.SESSION_RETENTION_DAYS > 0:
        results["sessions_deleted"] = cleanup_expired_sessions(max_age_days=config.SESSION_RETENTION_DAYS)
    if config.REQUEST_RETENTION_DAYS > 0:
        from src.services.service_requests import get_request_store

        results["requests_deleted"] = get_request_store().purge_closed_older_than_days(config.REQUEST_RETENTION_DAYS)
    if backup_due(now):
        backup_path = backups.backup_all(write_lock=index_write_lock())
        results["backup_path"] = backup_path
        results["backups_pruned"] = backups.prune_full_backups(config.BACKUP_KEEP)
        audit_logger.log(
            username="system",
            role="system",
            action="backup_create",
            detail=f"Scheduled full backup created at: {backup_path}",
            status="success",
        )
    return results


async def maintenance_loop(interval_seconds: int = MAINTENANCE_INTERVAL_SECONDS) -> None:
    """Run maintenance now and then every `interval_seconds` until cancelled."""
    while True:
        try:
            results = await asyncio.to_thread(run_maintenance_once)
            if results:
                logger.info(f"[Maintenance] {results}")
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed run (e.g. full disk) must not stop later runs or the API
            logger.exception("[Maintenance] Scheduled maintenance failed")
        await asyncio.sleep(interval_seconds)
