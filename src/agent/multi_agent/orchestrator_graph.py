import os
import threading
from typing import Optional, Dict, Any, Generator
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agent.llm import create_chat_model
from src.agent.multi_agent.state import MultiAgentState
from src.agent.multi_agent.registry import AgentRegistry, agent_registry
from src.agent.multi_agent.supervisor import SupervisorAgent
import src.agent.multi_agent.sub_agents  # noqa: F401  Ensures built-in sub-agents are loaded & registered
from src.core.config import CHAT_HISTORY_MAX_TURNS, MULTI_AGENT_CONVERSATIONS_DB
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Orchestrator")

RECORD_TURN_NODE = "record_turn"


class MultiAgentOrchestrator:
    """Enterprise Multi-Agent Orchestrator compiling and executing the LangGraph Supervisor-Worker workflow.

    Workflow: supervisor -> (specialist agent | direct answer) -> record_turn -> END.
    record_turn appends the finished turn to chat_history, which the checkpointer persists per thread_id.
    Batch (query) and streaming (stream_events) execution run the same compiled graph.
    """

    def __init__(
        self,
        chat_model=None,
        registry: Optional[AgentRegistry] = None,
        checkpointer=None,
    ):
        self.chat_model = chat_model or create_chat_model()
        self.registry = registry or agent_registry
        self.supervisor = SupervisorAgent(chat_model=self.chat_model, registry=self.registry)
        self._sqlite_conn = None
        self.checkpointer = checkpointer or self._init_default_checkpointer()
        self._graph_lock = threading.Lock()
        self._compile_graphs()

    def _compile_graphs(self) -> None:
        """(Re)compile the workflow for the agents currently in the registry."""
        self._compiled_registry_version = self.registry.version
        self.app = self._build_graph(checkpointer=self.checkpointer)
        # Session-less queries run without a checkpointer (a checkpointer requires a thread_id)
        self._stateless_app = self._build_graph(checkpointer=None)

    def _ensure_current_graph(self) -> None:
        """Recompile if agents were registered or unregistered since the graph was built.

        Conversation state lives in the checkpointer, so recompiling does not lose sessions.
        """
        if self._compiled_registry_version == self.registry.version:
            return
        with self._graph_lock:
            if self._compiled_registry_version != self.registry.version:
                logger.info("[Orchestrator] Agent registry changed, recompiling workflow.")
                self._compile_graphs()

    def _init_default_checkpointer(self):
        """Initialize SQLite checkpointer for multi-agent multi-turn conversation persistence."""
        try:
            import sqlite3
            from langgraph.checkpoint.sqlite import SqliteSaver

            os.makedirs(os.path.dirname(MULTI_AGENT_CONVERSATIONS_DB), exist_ok=True)
            conn = sqlite3.connect(MULTI_AGENT_CONVERSATIONS_DB, check_same_thread=False)
            self._sqlite_conn = conn
            saver = SqliteSaver(conn)
            saver.setup()
            logger.info(f"[Orchestrator] Multi-agent checkpointer initialized at: {MULTI_AGENT_CONVERSATIONS_DB}")
            return saver
        except Exception as e:
            logger.warning(f"[Orchestrator] Could not initialize SqliteSaver, using MemorySaver: {e}")
            return MemorySaver()

    @staticmethod
    def _record_turn(state: MultiAgentState) -> Dict[str, Any]:
        """Append the completed turn to the persisted conversation history."""
        raw_agent = state.get("next_agent", "finish")
        active_agent = "supervisor" if raw_agent in ("finish", "", None) else raw_agent
        history = list(state.get("chat_history", []))
        history.append(
            {
                "question": state.get("question", ""),
                "answer": state.get("final_answer", ""),
                "agent": active_agent,
            }
        )
        return {
            "chat_history": history[-CHAT_HISTORY_MAX_TURNS:],
            "active_agent": active_agent,
        }

    def _build_graph(self, checkpointer=None):
        """Compile the dynamic LangGraph StateGraph with Supervisor routing and registered worker nodes."""
        workflow = StateGraph(MultiAgentState)

        # 1. Add Supervisor Router Node
        workflow.add_node("supervisor", self.supervisor.route)
        workflow.set_entry_point("supervisor")
        workflow.add_node(RECORD_TURN_NODE, self._record_turn)
        workflow.add_edge(RECORD_TURN_NODE, END)

        # 2. Add each registered sub-agent as a worker node
        registered_agents = self.registry.list_agents()
        agent_names = [agent.name for agent in registered_agents]

        for agent in registered_agents:
            # Inject shared chat_model to sub-agent if not already initialized
            if agent._chat_model is None:
                agent.chat_model = self.chat_model

            workflow.add_node(agent.name, agent.execute)
            # Once a specialist agent finishes execution, persist the turn and terminate the flow
            workflow.add_edge(agent.name, RECORD_TURN_NODE)

        # 3. Define conditional routing edge from Supervisor
        def route_decision(state: MultiAgentState) -> str:
            target = state.get("next_agent", "finish")
            if target in agent_names:
                return target
            return "finish"

        # Edge routing mapping
        edge_mapping = {name: name for name in agent_names}
        edge_mapping["finish"] = RECORD_TURN_NODE

        workflow.add_conditional_edges("supervisor", route_decision, edge_mapping)

        # 4. Compile (with checkpointer for persistent sessions)
        app = workflow.compile(checkpointer=checkpointer) if checkpointer else workflow.compile()
        logger.info(f"[Orchestrator] Compiled MultiAgent workflow with {len(agent_names)} sub-agents: {agent_names}")
        return app

    @staticmethod
    def _turn_input(question: str, forced_agent: Optional[str]) -> MultiAgentState:
        """Per-turn input. Every non-persistent key is reset so values never leak from the previous turn."""
        return {
            "question": question,
            "forced_agent": forced_agent,
            "next_agent": "",
            "active_agent": "",
            "agent_trace": [],
            "sources": [],
            "final_answer": "",
            "hallucination_grade": "",
            "is_refined": False,
        }

    def _app_and_config(self, thread_id: Optional[str]):
        self._ensure_current_graph()
        if thread_id:
            return self.app, {"configurable": {"thread_id": thread_id}}
        return self._stateless_app, {}

    @staticmethod
    def _to_result(state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "answer": state.get("final_answer", ""),
            "sources": state.get("sources", []),
            "agent_trace": state.get("agent_trace", []),
            "active_agent": state.get("active_agent") or "supervisor",
            "hallucination_grade": state.get("hallucination_grade", ""),
            "is_refined": state.get("is_refined", False),
            "chat_history": state.get("chat_history", []),
        }

    def query(
        self,
        question: str,
        thread_id: Optional[str] = None,
        forced_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the multi-agent workflow and return verified answer, sources, and agent trace."""
        app, config = self._app_and_config(thread_id)
        result = app.invoke(self._turn_input(question, forced_agent), config=config)
        return self._to_result(result)

    def stream_events(
        self,
        question: str,
        thread_id: Optional[str] = None,
        forced_agent: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Stream real-time multi-agent execution events with intermediate status and final response.

        Runs the same compiled graph as query(), so memory and forced routing behave identically.
        Closing the generator stops execution before the next graph node starts.
        """
        yield {
            "type": "status",
            "message": "👑 Supervisor: Analyzing query and routing to the optimal specialist agent...",
            "node": "supervisor",
        }

        app, config = self._app_and_config(thread_id)
        final_state: Dict[str, Any] = {}

        for chunk in app.stream(
            self._turn_input(question, forced_agent),
            config=config,
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                update = update or {}
                final_state.update(update)

                if node == "supervisor":
                    target_agent = update.get("next_agent", "finish")
                    sub_agent = self.registry.get(target_agent)
                    if sub_agent is None:
                        yield {
                            "type": "agent_selected",
                            "agent": "supervisor",
                            "display_name": "Supervisor Orchestrator",
                            "reason": "General query or greeting handled directly by Supervisor.",
                        }
                        continue
                    display_name = sub_agent.display_name or target_agent
                    yield {
                        "type": "agent_selected",
                        "agent": target_agent,
                        "display_name": display_name,
                        "reason": f"Task delegated to specialist: '{display_name}'.",
                    }
                    yield {
                        "type": "status",
                        "message": f"🤖 {display_name}: Executing specialized task...",
                        "node": target_agent,
                    }
                elif node != RECORD_TURN_NODE:
                    yield {"type": "sources", "sources": update.get("sources", [])}

        result = self._to_result(final_state)
        yield {
            "type": "done",
            "answer": result["answer"],
            "sources": result["sources"],
            "agent_trace": result["agent_trace"],
            "active_agent": result["active_agent"],
            "hallucination_grade": result["hallucination_grade"],
            "is_refined": result["is_refined"],
        }

    def cleanup(self):
        """Gracefully release checkpointer SQLite database connection."""
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
                logger.info("[Orchestrator] Multi-agent checkpointer connection closed.")
            except Exception as e:
                logger.warning(f"[Orchestrator] Error closing checkpointer connection: {e}")
            finally:
                self._sqlite_conn = None
