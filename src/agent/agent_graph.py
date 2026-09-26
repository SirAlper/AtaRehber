import os
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from src.agent.llm import create_chat_model
from src.rag.rag_engine import RAGEngine
from src.agent.nodes import AgentNodes
from src.agent.query_service import QueryService
from src.core.logger import get_logger

logger = get_logger("AgentGraph")


class AgentState(TypedDict, total=False):
    question: str
    search_query: str
    context: str
    sources: List[Dict[str, Any]]
    answer: str
    hallucination_grade: str
    retry_count: int
    is_refined: bool
    chat_history: List[Dict[str, str]]


class EnterpriseRAGAgent:
    """Orchestrator class that sets up the LangGraph workflow and initializes the query service."""

    def __init__(self, rag_engine: RAGEngine, checkpointer=None, chat_model=None):
        self.rag_engine = rag_engine
        self.chat_model = chat_model or create_chat_model()
        self.nodes = AgentNodes(self.chat_model, self.rag_engine)
        self._sqlite_conn = None  # Track connection for cleanup (set by _init_default_checkpointer)
        self.checkpointer = checkpointer or self._init_default_checkpointer()
        self.app = self._build_graph()
        self.service = QueryService(self.app, self.nodes, self.chat_model)

    def _init_default_checkpointer(self):
        """Initialize SQLite checkpointer for conversation memory persistence."""
        try:
            import sqlite3
            from langgraph.checkpoint.sqlite import SqliteSaver
            from src.core.config import DOCS_PATH

            os.makedirs(DOCS_PATH, exist_ok=True)
            db_path = os.path.join(DOCS_PATH, "conversations.db")
            conn = sqlite3.connect(db_path, check_same_thread=False)
            self._sqlite_conn = conn  # Store reference for cleanup
            saver = SqliteSaver(conn)
            saver.setup()
            logger.info(f"Initialized conversation checkpointer at {db_path}")
            return saver
        except Exception as e:
            logger.warning(f"Could not initialize SqliteSaver, falling back to MemorySaver: {e}")
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()

    def _build_graph(self):
        """Configure and compile the LangGraph state workflow with checkpointer."""
        workflow = StateGraph(AgentState)

        workflow.add_node("rewrite", self.nodes.rewrite_query)
        workflow.add_node("retrieve", self.nodes.retrieve)
        workflow.add_node("generate", self.nodes.generate)
        workflow.add_node("grade", self.nodes.grade_hallucination)
        workflow.add_node("refine", self.nodes.refine)
        workflow.add_node("fallback", self.nodes.fallback)

        workflow.set_entry_point("rewrite")
        workflow.add_edge("rewrite", "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "grade")
        workflow.add_conditional_edges(
            "grade",
            self.nodes.decide_hallucinate,
            {"end": END, "refine": "refine", "fallback": "fallback"},
        )
        workflow.add_edge("refine", "grade")
        workflow.add_edge("fallback", END)

        if self.checkpointer:
            return workflow.compile(checkpointer=self.checkpointer)
        return workflow.compile()

    # ──────────────────────────── QUERY SERVICE BRIDGES ────────────────────────────

    def query(self, question: str, thread_id: Optional[str] = None) -> dict:
        """Run batch query through the LangGraph workflow."""
        return self.service.query(question, thread_id=thread_id)

    def stream_events(self, question: str, thread_id: Optional[str] = None):
        """Stream stage status events and final answer."""
        return self.service.stream_events(question, thread_id=thread_id)

    def stream_query(self, question: str, thread_id: Optional[str] = None):
        """Stream final answer upon completion."""
        return self.service.stream_query(question, thread_id=thread_id)

    # ──────────────────────────── RESOURCE CLEANUP ────────────────────────────

    def cleanup(self):
        """Release resources held by the agent (SQLite connections, etc.)."""
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
                logger.info("Conversation checkpointer SQLite connection closed.")
            except Exception as e:
                logger.warning(f"Error closing SQLite connection: {e}")
            self._sqlite_conn = None
