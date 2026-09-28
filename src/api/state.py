import asyncio
import os
from typing import Any, Optional

from src.rag.document_loader import DocumentLoader
from src.rag.rag_engine import RAGEngine
from src.agent.llm import check_ollama, create_chat_model
from src.connectors.db_connector import DatabaseConnector
from src.connectors.sample_db import create_sample_sqlite_db
from src.connectors.db_loader import DatabaseTableLoader
from src.core.config import (
    DOCS_PATH,
    DATABASE_URL,
    DEFAULT_SQLITE_URL,
    SAMPLE_DB_PATH,
    SAMPLE_DB_ENABLED,
    ALLOWED_UPLOAD_EXTENSIONS,
    OLLAMA_NUM_PARALLEL,
)
from src.auth.document_access import access_metadata, document_access_store
from src.core import config
from src.core.logger import get_logger
from src.services.backups import apply_pending_restore

logger = get_logger("API.State")

# Lazy initialized singletons
chat_model: Optional[Any] = None
rag_engine: Optional[RAGEngine] = None
multi_agent_orchestrator: Optional[Any] = None
document_loader: Optional[DocumentLoader] = None
db_connector: Optional[DatabaseConnector] = None
db_loader: Optional[DatabaseTableLoader] = None
ollama_semaphore = asyncio.Semaphore(OLLAMA_NUM_PARALLEL)


class QueueFullError(Exception):
    """More than MAX_QUEUED_QUERIES questions are already waiting for the model."""


class QueryConcurrencyManager:
    """Limits concurrent queries to OLLAMA_NUM_PARALLEL so the Ollama server is not overloaded.

    At most MAX_QUEUED_QUERIES questions wait for a slot; entering beyond that raises QueueFullError at once, so
    a user sees "busy, try again shortly" instead of a timeout minutes later.
    """

    def __init__(self):
        self.waiting = 0

    def is_full(self) -> bool:
        limit = config.MAX_QUEUED_QUERIES
        return limit > 0 and ollama_semaphore.locked() and self.waiting >= limit

    async def __aenter__(self):
        if self.is_full():
            raise QueueFullError()
        self.waiting += 1
        try:
            await ollama_semaphore.acquire()
        finally:
            self.waiting -= 1
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
        use_sample = SAMPLE_DB_ENABLED and os.path.exists(SAMPLE_DB_PATH)
        database_url = DATABASE_URL or (DEFAULT_SQLITE_URL if use_sample else "")
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
    access = document_access_store.all()
    for filename in unindexed:
        file_path = os.path.join(DOCS_PATH, filename)
        chunks, ids, metadatas = loader.load_and_chunk_file(file_path)
        # Documents restricted to groups (e.g. re-indexed after a vector store restore) stay restricted
        if access.get(filename):
            for metadata in metadatas:
                metadata.update(access_metadata(access[filename]))
        if chunks:
            engine.add_documents(chunks, ids, metadatas)
            logger.info(f"  ✓ '{filename}' -> {len(chunks)} chunks indexed.")
        else:
            logger.warning(f"  ✗ '{filename}' -> no parseable text found.")

    logger.info("[Auto-Indexing] Completed successfully!")


def init_services():
    """Initialize all backend services and sample database on application startup."""
    logger.info("Initializing Enterprise RAG services...")

    apply_pending_restore(vector_store_open=rag_engine is not None)

    if SAMPLE_DB_ENABLED and not DATABASE_URL and not os.path.exists(SAMPLE_DB_PATH):
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
    # Agents defined in the web UI; the orchestrator recompiles its workflow when the registry changes
    from src.agent.multi_agent.custom_agents import sync_custom_agents

    logger.info(f"[Agents] {sync_custom_agents()} custom agent(s) loaded.")

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
    global db_connector, multi_agent_orchestrator
    logger.info("Cleaning up Enterprise RAG services...")

    if multi_agent_orchestrator is not None:
        try:
            multi_agent_orchestrator.cleanup()
            logger.info("Multi-agent orchestrator resources released.")
        except Exception as e:
            logger.warning(f"Error cleaning up multi-agent orchestrator: {e}")

    if db_connector is not None and db_connector.engine is not None:
        try:
            db_connector.engine.dispose()
            logger.info("Database engine disposed.")
        except Exception as e:
            logger.warning(f"Error disposing database engine: {e}")

    logger.info("Enterprise RAG services shutdown complete.")


def index_write_lock():
    """The vector store's write lock once it is open (pauses index writes during backups), else None."""
    return rag_engine.write_lock if rag_engine is not None else None
