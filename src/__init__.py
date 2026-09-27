"""OpenLocalRagAgents Package.

Modular Architecture:
- src.core: System configuration and environment settings
- src.rag: Contextual document loader and vector search engine
- src.agent: LLM pipeline, prompts, LangGraph workflow, and query service
- src.connectors: Universal database connector and table vectorizer
- src.api: FastAPI REST API gateway
"""

from src.core.config import (
    BASE_DIR,
    MODELS_DIR,
    VECTOR_DB_PATH,
    DOCS_PATH,
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
)
from src.rag.document_loader import DocumentLoader
from src.rag.rag_engine import RAGEngine
from src.agent.agent_graph import EnterpriseRAGAgent

__all__ = [
    "BASE_DIR",
    "MODELS_DIR",
    "VECTOR_DB_PATH",
    "DOCS_PATH",
    "EMBEDDING_MODEL_NAME",
    "RERANKER_MODEL_NAME",
    "DocumentLoader",
    "RAGEngine",
    "EnterpriseRAGAgent",
]
