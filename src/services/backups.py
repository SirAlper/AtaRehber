"""Full backups, staged vector index restores, and backup housekeeping.

A full backup holds the vector index (vector_db/) and the data directory (documents, users, audit log,
conversations, service requests). Restoring the index is staged and applied at the next start, because the live
ChromaDB directory must not be replaced while the server has it open.
"""

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from src.core.config import DOCS_PATH, VECTOR_DB_PATH
from src.core.logger import get_logger

logger = get_logger("Services.Backups")

BACKUP_DIR = os.path.join(os.path.dirname(VECTOR_DB_PATH), "backups")
FULL_BACKUP_PREFIX = "full_backup_"
# Index-only backups written by earlier versions; still listed and restorable
BACKUP_PREFIX = "vector_db_backup_"
_BACKUP_TIME_FORMAT = "%Y%m%d_%H%M%S"
# Never copied into backups: the JWT signing secret (a restored system simply issues new tokens) and
# SQLite side files (the databases are copied with the SQLite backup API instead)
_BACKUP_EXCLUDED_FILES = {".jwt_secret"}
_BACKUP_EXCLUDED_SUFFIXES = ("-wal", "-shm", "-journal")
# Kept inside the backups directory so a staged restore survives container re-creation
PENDING_RESTORE_PATH = os.path.join(BACKUP_DIR, ".restore_pending")


def is_valid_backup_name(name: str) -> bool:
    """Backup names must be plain directory names created by this module."""
    return (
        bool(name)
        and name == os.path.basename(name)
        and name.startswith((BACKUP_PREFIX, FULL_BACKUP_PREFIX))
        and ".." not in name
    )


def _copy_data_dir(src_dir: str, dst_dir: str) -> None:
    """Copy the data directory. SQLite databases are copied with the backup API, so a snapshot taken while
    the server writes (audit log, conversations) is still consistent."""
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if name in _BACKUP_EXCLUDED_FILES or name.endswith(_BACKUP_EXCLUDED_SUFFIXES):
            continue
        if os.path.isdir(src):
            _copy_data_dir(src, dst)
        elif name.endswith(".db"):
            source, target = sqlite3.connect(src), sqlite3.connect(dst)
            try:
                source.backup(target)
            finally:
                source.close()
                target.close()
        else:
            shutil.copy2(src, dst)


def backup_all(backup_dir: Optional[str] = None, write_lock=None) -> str:
    """Create a full backup and return its directory.

    write_lock: the vector store's write lock (RAGEngine.write_lock); index writes are paused while it is copied.
    Restoring the data directory requires stopping the server (see docs/docker_deployment.md); the index part
    can also be restored through the admin API.
    """
    backup_dir = backup_dir or BACKUP_DIR
    timestamp = datetime.now(timezone.utc).strftime(_BACKUP_TIME_FORMAT)
    backup_path = os.path.join(backup_dir, f"{FULL_BACKUP_PREFIX}{timestamp}")
    os.makedirs(backup_path)
    try:
        if write_lock is not None:
            with write_lock:
                shutil.copytree(VECTOR_DB_PATH, os.path.join(backup_path, "vector_db"))
        elif os.path.isdir(VECTOR_DB_PATH):
            shutil.copytree(VECTOR_DB_PATH, os.path.join(backup_path, "vector_db"))
        if os.path.isdir(DOCS_PATH):
            _copy_data_dir(DOCS_PATH, os.path.join(backup_path, "data"))
    except Exception:
        shutil.rmtree(backup_path, ignore_errors=True)
        logger.exception("[Backup] Full backup failed")
        raise
    logger.info(f"[Backup] Full backup created at: {backup_path}")
    return backup_path


def restore_vector_db(backup_path: str) -> bool:
    """Stage a backup to replace the vector database on the next server start.

    The live ChromaDB directory is never modified while the server has it open;
    apply_pending_restore() swaps it in during startup before the index is loaded.
    """
    if not os.path.isdir(backup_path):
        logger.error(f"[Restore] Backup path does not exist: {backup_path}")
        return False
    # Full backups keep the index in a vector_db/ subdirectory
    if os.path.isdir(os.path.join(backup_path, "vector_db")):
        backup_path = os.path.join(backup_path, "vector_db")

    try:
        if os.path.exists(PENDING_RESTORE_PATH):
            shutil.rmtree(PENDING_RESTORE_PATH)
        shutil.copytree(backup_path, PENDING_RESTORE_PATH)
        logger.info(f"[Restore] Staged restore from '{backup_path}'. It will be applied on next restart.")
        return True
    except Exception as e:
        logger.error(f"[Restore] Failed to stage restore: {e}")
        return False


def _move_directory_contents(src_dir: str, dst_dir: str) -> None:
    """Move every entry of src_dir into dst_dir (which is created if needed)."""
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        shutil.move(os.path.join(src_dir, name), os.path.join(dst_dir, name))


def apply_pending_restore(vector_store_open: bool = False) -> bool:
    """Swap a staged restore into place. Must run before the RAG engine opens the vector store.

    Only the directory *contents* are moved, never the vector_db directory itself, because in
    Docker it is a bind-mount point that cannot be renamed. The replaced database is kept as a
    'pre_restore_' directory in the backups folder.
    """
    if not os.path.isdir(PENDING_RESTORE_PATH):
        return False
    if vector_store_open:
        logger.error("[Restore] Vector store already open; pending restore will be applied on next restart.")
        return False

    timestamp = datetime.now(timezone.utc).strftime(_BACKUP_TIME_FORMAT)
    try:
        if os.path.isdir(VECTOR_DB_PATH) and os.listdir(VECTOR_DB_PATH):
            _move_directory_contents(VECTOR_DB_PATH, os.path.join(BACKUP_DIR, f"pre_restore_{timestamp}"))
        _move_directory_contents(PENDING_RESTORE_PATH, VECTOR_DB_PATH)
        os.rmdir(PENDING_RESTORE_PATH)
        logger.info("[Restore] Pending vector database restore applied.")
        return True
    except Exception as e:
        logger.error(f"[Restore] Failed to apply pending restore: {e}")
        return False


def list_backups(backup_dir: Optional[str] = None) -> list:
    """Full and index-only backups, newest first."""
    backup_dir = backup_dir or BACKUP_DIR
    if not os.path.exists(backup_dir):
        return []

    backups = []
    for name in os.listdir(backup_dir):
        path = os.path.join(backup_dir, name)
        if os.path.isdir(path) and name.startswith((BACKUP_PREFIX, FULL_BACKUP_PREFIX)):
            stat = os.stat(path)
            backups.append(
                {
                    "name": name,
                    "type": "full" if name.startswith(FULL_BACKUP_PREFIX) else "vector_db",
                    "path": path,
                    "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                }
            )
    # Names embed a sortable UTC timestamp
    return sorted(backups, key=lambda b: b["name"].split("_backup_")[-1], reverse=True)


def latest_full_backup_time(backup_dir: Optional[str] = None) -> Optional[datetime]:
    """UTC time of the newest full backup (from its name), or None."""
    backup_dir = backup_dir or BACKUP_DIR
    if not os.path.isdir(backup_dir):
        return None
    times = []
    for name in os.listdir(backup_dir):
        if name.startswith(FULL_BACKUP_PREFIX):
            try:
                stamp = name[len(FULL_BACKUP_PREFIX) :]
                times.append(datetime.strptime(stamp, _BACKUP_TIME_FORMAT).replace(tzinfo=timezone.utc))
            except ValueError:
                continue
    return max(times, default=None)


def prune_full_backups(keep: int, backup_dir: Optional[str] = None) -> int:
    """Delete all but the newest `keep` full backups. Index-only and pre-restore backups are left alone."""
    backup_dir = backup_dir or BACKUP_DIR
    if keep < 1 or not os.path.isdir(backup_dir):
        return 0
    full = sorted((n for n in os.listdir(backup_dir) if n.startswith(FULL_BACKUP_PREFIX)), reverse=True)
    for name in full[keep:]:
        shutil.rmtree(os.path.join(backup_dir, name), ignore_errors=True)
    return len(full[keep:])
