import os
import asyncio
import shutil
from datetime import datetime, timezone
from typing import Optional, Any

from src.rag.document_loader import DocumentLoader
from src.rag.rag_engine import RAGEngine
from src.agent.agent_graph import EnterpriseRAGAgent
from src.agent.llm import check_ollama, create_chat_model
from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db
from src.connectors.db_loader import DatabaseTableLoader
from src.core.config import (
    DOCS_PATH,
    DATABASE_URL,
    DEFAULT_SQLITE_URL,
    SAMPLE_DB_PATH,
    ALLOWED_UPLOAD_EXTENSIONS,
    OLLAMA_NUM_PARALLEL,
    VECTOR_DB_PATH,
)
from src.core.logger import get_logger

logger = get_logger("API.State")

# Lazy initialized singletons
chat_model: Optional[Any] = None
rag_engine: Optional[RAGEngine] = None
agent: Optional[EnterpriseRAGAgent] = None
multi_agent_orchestrator: Optional[Any] = None
document_loader: Optional[DocumentLoader] = None
db_connector: Optional[DatabaseConnector] = None
db_loader: Optional[DatabaseTableLoader] = None
ollama_semaphore = asyncio.Semaphore(OLLAMA_NUM_PARALLEL)


class QueryConcurrencyManager:
    """Limits concurrent queries to OLLAMA_NUM_PARALLEL so the Ollama server is not overloaded."""

    async def __aenter__(self):
        await ollama_semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        ollama_semaphore.release()


query_concurrency_gate = QueryConcurrencyManager()


def get_rag_engine() -> RAGEngine:
    global rag_engine
    if rag_engine is None:
        rag_engine = RAGEngine()
    return rag_engine


def get_chat_model():
    """Shared chat model so the LLM weights are loaded into memory only once."""
    global chat_model
    if chat_model is None:
        chat_model = create_chat_model()
    return chat_model


def get_agent() -> EnterpriseRAGAgent:
    """Legacy single-agent Self-RAG workflow (not used by the API query endpoints)."""
    global agent
    if agent is None:
        agent = EnterpriseRAGAgent(get_rag_engine(), chat_model=get_chat_model())
    return agent


def get_multi_agent_orchestrator():
    global multi_agent_orchestrator
    if multi_agent_orchestrator is None:
        from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator

        multi_agent_orchestrator = MultiAgentOrchestrator(chat_model=get_chat_model())
    return multi_agent_orchestrator


def get_document_loader() -> DocumentLoader:
    global document_loader
    if document_loader is None:
        document_loader = DocumentLoader(DOCS_PATH)
    return document_loader


def get_db_connector() -> DatabaseConnector:
    global db_connector
    if db_connector is None:
        # Resolved here rather than at import time: on a fresh install the sample database is
        # only created by init_services(), after config was loaded.
        database_url = DATABASE_URL or (DEFAULT_SQLITE_URL if os.path.exists(SAMPLE_DB_PATH) else "")
        db_connector = DatabaseConnector(database_url=database_url)
    return db_connector


def get_db_loader() -> DatabaseTableLoader:
    global db_loader
    if db_loader is None:
        db_loader = DatabaseTableLoader(get_db_connector())
    return db_loader


def auto_index_on_startup():
    """Scan data/ folder on server startup and automatically index any unindexed documents into ChromaDB."""
    if not os.path.exists(DOCS_PATH):
        os.makedirs(DOCS_PATH, exist_ok=True)
        return

    engine = get_rag_engine()
    loader = get_document_loader()
    db_stats = engine.get_stats()
    indexed_files = set(db_stats.get("document_chunks", {}).keys())

    data_files = [
        f
        for f in os.listdir(DOCS_PATH)
        if os.path.isfile(os.path.join(DOCS_PATH, f)) and os.path.splitext(f)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS
    ]

    unindexed = [f for f in data_files if f not in indexed_files]

    if not unindexed:
        logger.info(f"[Auto-Indexing] No unindexed documents found in data/. ({len(indexed_files)} files indexed)")
        return

    logger.info(f"[Auto-Indexing] Detected {len(unindexed)} new document(s), indexing...")
    for filename in unindexed:
        file_path = os.path.join(DOCS_PATH, filename)
        chunks, ids, metadatas = loader.load_and_chunk_file(file_path)
        if chunks:
            engine.add_documents(chunks, ids, metadatas)
            logger.info(f"  ✓ '{filename}' -> {len(chunks)} chunks indexed.")
        else:
            logger.warning(f"  ✗ '{filename}' -> no parseable text found.")

    logger.info("[Auto-Indexing] Completed successfully!")


def init_services():
    """Initialize all backend services and sample database on application startup."""
    logger.info("Initializing Enterprise RAG services...")

    apply_pending_restore()

    if not DATABASE_URL and not os.path.exists(SAMPLE_DB_PATH):
        try:
            create_sample_sqlite_db(SAMPLE_DB_PATH)
            logger.info(f"Sample database created at '{SAMPLE_DB_PATH}'.")
        except Exception as e:
            logger.warning(f"Could not create sample database: {e}")

    get_rag_engine()
    get_document_loader()
    get_db_connector()
    get_db_loader()
    get_multi_agent_orchestrator()

    # The API still starts without Ollama (documents, users, audit work); queries fail until it is available
    llm_problem = check_ollama()
    if llm_problem:
        logger.error(f"[LLM] {llm_problem}")
    else:
        logger.info("[LLM] Ollama server reachable and model available.")

    auto_index_on_startup()
    logger.info("Enterprise RAG services initialized successfully.")


def cleanup_services():
    """Gracefully release all resources on application shutdown."""
    global agent, db_connector, multi_agent_orchestrator
    logger.info("Cleaning up Enterprise RAG services...")

    if multi_agent_orchestrator is not None:
        try:
            multi_agent_orchestrator.cleanup()
            logger.info("Multi-agent orchestrator resources released.")
        except Exception as e:
            logger.warning(f"Error cleaning up multi-agent orchestrator: {e}")

    if agent is not None:
        agent.cleanup()
        logger.info("Agent resources released.")

    if db_connector is not None and db_connector.engine is not None:
        try:
            db_connector.engine.dispose()
            logger.info("Database engine disposed.")
        except Exception as e:
            logger.warning(f"Error disposing database engine: {e}")

    logger.info("Enterprise RAG services shutdown complete.")


# ──────────────────────────── SESSION MANAGEMENT ────────────────────────────


def cleanup_expired_sessions(max_age_days: int = 30) -> int:
    """Remove multi-agent conversation threads inactive for more than max_age_days.

    Returns the number of deleted threads.
    """
    from src.agent.multi_agent.sessions import cleanup_expired_sessions as _cleanup

    return _cleanup(max_age_days=max_age_days)


# ──────────────────────────── VECTOR DB BACKUP/RESTORE ────────────────────────────

BACKUP_DIR = os.path.join(os.path.dirname(VECTOR_DB_PATH), "backups")
BACKUP_PREFIX = "vector_db_backup_"
# Full backups: vector_db/ (the index) and data/ (documents, users, audit log, conversations)
FULL_BACKUP_PREFIX = "full_backup_"
_BACKUP_TIME_FORMAT = "%Y%m%d_%H%M%S"
# Never copied into backups: the JWT signing secret (a restored system simply issues new tokens) and
# SQLite side files (the databases are copied with the SQLite backup API instead)
_BACKUP_EXCLUDED_FILES = {".jwt_secret"}
_BACKUP_EXCLUDED_SUFFIXES = ("-wal", "-shm", "-journal")
# Kept inside the backups directory so a staged restore survives container re-creation
PENDING_RESTORE_PATH = os.path.join(BACKUP_DIR, ".restore_pending")


def is_valid_backup_name(name: str) -> bool:
    """Backup names must be plain directory names created by backup_vector_db or backup_all."""
    return (
        bool(name)
        and name == os.path.basename(name)
        and name.startswith((BACKUP_PREFIX, FULL_BACKUP_PREFIX))
        and ".." not in name
    )


def backup_vector_db(backup_dir: Optional[str] = None) -> str:
    """Create a timestamped backup of the ChromaDB vector database.

    Index writes are paused while copying so the snapshot is consistent.
    Returns the path to the backup directory.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if backup_dir is None:
        backup_dir = BACKUP_DIR

    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"{BACKUP_PREFIX}{timestamp}")

    try:
        write_lock = rag_engine.write_lock if rag_engine is not None else None
        if write_lock is not None:
            with write_lock:
                shutil.copytree(VECTOR_DB_PATH, backup_path)
        else:
            shutil.copytree(VECTOR_DB_PATH, backup_path)
        logger.info(f"[Backup] Vector database backed up to: {backup_path}")
        return backup_path
    except FileNotFoundError:
        logger.error("[Backup] Vector database directory not found.")
        raise
    except Exception as e:
        logger.error(f"[Backup] Failed to backup vector database: {e}")
        raise


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


def apply_pending_restore() -> bool:
    """Swap a staged restore into place. Must run before the RAG engine opens the vector store.

    Only the directory *contents* are moved, never the vector_db directory itself, because in
    Docker it is a bind-mount point that cannot be renamed. The replaced database is kept as a
    'pre_restore_' directory in the backups folder.
    """
    if not os.path.isdir(PENDING_RESTORE_PATH):
        return False
    if rag_engine is not None:
        logger.error("[Restore] Vector store already open; pending restore will be applied on next restart.")
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
    """List available vector database backups."""
    if backup_dir is None:
        backup_dir = BACKUP_DIR

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

    # Newest first; names embed a sortable UTC timestamp
    return sorted(backups, key=lambda b: b["name"].split("_backup_")[-1], reverse=True)


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
            import sqlite3

            source, target = sqlite3.connect(src), sqlite3.connect(dst)
            try:
                source.backup(target)
            finally:
                source.close()
                target.close()
        else:
            shutil.copy2(src, dst)


def backup_all(backup_dir: Optional[str] = None) -> str:
    """Create a full backup: the vector index plus the data directory (documents, users, audit log,
    conversations, sample database). Returns the backup directory.

    Restoring the data directory requires stopping the server (see docs/docker_deployment.md);
    the vector index part can also be restored through the admin API.
    """
    backup_dir = backup_dir or BACKUP_DIR
    timestamp = datetime.now(timezone.utc).strftime(_BACKUP_TIME_FORMAT)
    backup_path = os.path.join(backup_dir, f"{FULL_BACKUP_PREFIX}{timestamp}")
    os.makedirs(backup_path)
    try:
        write_lock = rag_engine.write_lock if rag_engine is not None else None
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
    """Delete all but the newest `keep` full backups. Vector-only and pre-restore backups are left alone."""
    backup_dir = backup_dir or BACKUP_DIR
    if keep < 1 or not os.path.isdir(backup_dir):
        return 0
    full = sorted((n for n in os.listdir(backup_dir) if n.startswith(FULL_BACKUP_PREFIX)), reverse=True)
    for name in full[keep:]:
        shutil.rmtree(os.path.join(backup_dir, name), ignore_errors=True)
    return len(full[keep:])
