import os
import asyncio
import shutil
from datetime import datetime, timezone
from typing import Optional, Any

from src.rag.document_loader import DocumentLoader
from src.rag.rag_engine import RAGEngine
from src.agent.agent_graph import EnterpriseRAGAgent
from src.agent.llm import create_chat_model
from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db
from src.connectors.db_loader import DatabaseTableLoader
from src.core.config import (
    DOCS_PATH,
    DATABASE_URL,
    DEFAULT_SQLITE_URL,
    SAMPLE_DB_PATH,
    ALLOWED_UPLOAD_EXTENSIONS,
    LLM_BACKEND,
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
query_lock = asyncio.Lock()
ollama_semaphore = asyncio.Semaphore(OLLAMA_NUM_PARALLEL)


class QueryConcurrencyManager:
    """
    Manages query concurrency depending on LLM backend:
    - Ollama: allows up to OLLAMA_NUM_PARALLEL parallel requests.
    - HuggingFace: serializes to 1 active inference to protect GPU/RAM.
    """

    async def __aenter__(self):
        if LLM_BACKEND == "ollama":
            await ollama_semaphore.acquire()
        else:
            await query_lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if LLM_BACKEND == "ollama":
            ollama_semaphore.release()
        else:
            query_lock.release()


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
# Kept inside the backups directory so a staged restore survives container re-creation
PENDING_RESTORE_PATH = os.path.join(BACKUP_DIR, ".restore_pending")


def is_valid_backup_name(name: str) -> bool:
    """Backup names must be plain directory names created by backup_vector_db."""
    return bool(name) and name == os.path.basename(name) and name.startswith(BACKUP_PREFIX) and ".." not in name


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
    for name in sorted(os.listdir(backup_dir), reverse=True):
        path = os.path.join(backup_dir, name)
        if os.path.isdir(path) and name.startswith(BACKUP_PREFIX):
            stat = os.stat(path)
            backups.append(
                {
                    "name": name,
                    "path": path,
                    "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                }
            )

    return backups
