import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agent.language import response_language
from src.agent.llm import create_chat_model, grader_model_name, router_model_name
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.state import MultiAgentState
from src.agent.multi_agent.registry import AgentRegistry, agent_registry
from src.agent.multi_agent.supervisor import SupervisorAgent
from src.agent.grading import is_grade_passed
from src.agent.prompts import build_grader_messages, build_synthesis_messages
import src.agent.multi_agent.sub_agents  # noqa: F401  Ensures built-in sub-agents are loaded & registered
from src.core.config import (
    CHAT_HISTORY_MAX_TURNS,
    MAX_AGENT_HANDOFFS,
    MULTI_AGENT_CONVERSATIONS_DB,
    OLLAMA_MODEL,
)
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Orchestrator")

RECORD_TURN_NODE = "record_turn"
SYNTHESIZE_NODE = "synthesize"
# active_agent of a turn whose answer combines several agents
MULTI_AGENT = "multi_agent"
SUPERVISOR_DISPLAY_NAME = "Supervisor Orchestrator"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _effective_results(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Step results that count for the answer (a step handed off to another agent does not)."""
    return [r for r in state.get("step_results", []) if not r.get("superseded")]


def _last_status(trace: List[Dict[str, Any]], agent_name: str) -> str:
    for entry in reversed(trace):
        if entry.get("agent") == agent_name:
            return str(entry.get("status", "success"))
    return "success"


class MultiAgentOrchestrator:
    """Multi-Agent Orchestrator compiling and executing the LangGraph Supervisor-Worker workflow.

    Workflow: supervisor -> plan of 1..MAX_AGENT_STEPS agent steps -> (synthesize) -> record_turn -> END.
    - Each step runs one specialist agent on its own sub-question; steps run one after another.
    - Handoff: a step that fails (see BaseSubAgent.handoff_on) is handed to another agent once
      (MAX_AGENT_HANDOFFS); the failed step no longer counts for the answer.
    - Several useful steps are combined into one answer by the synthesize node.
    record_turn appends the finished turn to chat_history, which the checkpointer persists per thread_id.
    Batch (query) and streaming (stream_events) execution run the same compiled graph.
    """

    def __init__(
        self,
        chat_model=None,
        registry: Optional[AgentRegistry] = None,
        checkpointer=None,
        router_model=None,
        grader_model=None,
    ):
        self.chat_model = chat_model or create_chat_model()
        # Separate models per task only when configured; otherwise the answer model does everything
        self.router_model = router_model or (
            self.chat_model if router_model_name() == OLLAMA_MODEL else create_chat_model(router_model_name())
        )
        self.grader_model = grader_model or (
            self.chat_model if grader_model_name() == OLLAMA_MODEL else create_chat_model(grader_model_name())
        )
        self.registry = registry or agent_registry
        self.supervisor = SupervisorAgent(chat_model=self.router_model, registry=self.registry)
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

    # ──────────────────────────── GRAPH NODES ────────────────────────────

    @staticmethod
    def _active_agent(state: Dict[str, Any]) -> str:
        effective = _effective_results(state)
        if not effective:
            return "supervisor"
        if len(effective) == 1:
            return effective[0]["agent"]
        return MULTI_AGENT

    @classmethod
    def _record_turn(cls, state: MultiAgentState) -> Dict[str, Any]:
        """Append the completed turn to the persisted conversation history."""
        active_agent = cls._active_agent(state)
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

    def _make_step_node(self, agent: BaseSubAgent):
        """Graph node running `agent` on the current plan step, recording its result and any handoff."""

        def run_step(state: MultiAgentState) -> Dict[str, Any]:
            plan = [dict(step) for step in state.get("plan") or []]
            index = state.get("plan_index", 0)
            if index < len(plan) and plan[index]["agent"] == agent.name:
                step = plan[index]
            else:  # defensive: the graph only routes here for the current step
                step = {"agent": agent.name, "question": state.get("question", "")}
                plan.insert(index, step)

            output = agent.execute({**state, "question": step["question"]}) or {}
            trace = list(output.get("agent_trace", state.get("agent_trace", [])))
            status = _last_status(trace, agent.name)
            result = {
                "agent": agent.name,
                "display_name": agent.display_name or agent.name,
                "question": step["question"],
                "answer": output.get("final_answer", ""),
                "sources": output.get("sources", []),
                "status": status,
                "hallucination_grade": output.get("hallucination_grade", ""),
                "is_refined": output.get("is_refined", False),
            }
            if step.get("handoff_from"):
                result["handoff_from"] = step["handoff_from"]

            handoffs = state.get("handoff_count", 0)
            target, reason = self._handoff_target(agent, output, status, step, plan, handoffs)
            if target:
                result["superseded"] = True
                plan.insert(index + 1, {"agent": target, "question": step["question"], "handoff_from": agent.name})
                handoffs += 1
                trace.append(
                    {
                        "agent": "supervisor",
                        "display_name": SUPERVISOR_DISPLAY_NAME,
                        "action": "handoff",
                        "from_agent": agent.name,
                        "target_agent": target,
                        "reason": reason,
                        "duration_ms": 0,
                        "status": "success",
                        "timestamp": _now(),
                    }
                )
                logger.info(f"[Orchestrator] Handoff {agent.name} -> {target}: {reason}")

            update = {
                # Carried over unless the agent changes it (the request agent's draft awaiting confirmation)
                **({"pending_request": output["pending_request"]} if "pending_request" in output else {}),
                "plan": plan,
                "plan_index": index + 1,
                "step_results": list(state.get("step_results", [])) + [result],
                "handoff_count": handoffs,
                "agent_trace": trace,
                "final_answer": result["answer"],
                "sources": result["sources"],
                "hallucination_grade": result["hallucination_grade"],
                "is_refined": result["is_refined"],
            }
            return update

        run_step.__name__ = f"run_{agent.name}"
        return run_step

    def _handoff_target(
        self,
        agent: BaseSubAgent,
        output: Dict[str, Any],
        status: str,
        step: Dict[str, Any],
        plan: List[Dict[str, Any]],
        handoffs: int,
    ) -> Tuple[Optional[str], str]:
        """Agent that should retry this step, or (None, "")."""
        explicit = output.get("handoff")
        if isinstance(explicit, dict) and explicit.get("to"):
            target, reason = str(explicit["to"]), str(explicit.get("reason") or "requested by the agent")
        else:
            target = (agent.handoff_on or {}).get(status)
            reason = f"'{agent.name}' ended with status '{status}'"
        if not target or handoffs >= MAX_AGENT_HANDOFFS or target == agent.name:
            return None, ""
        if not self.registry.is_available(target):
            return None, ""
        # Never give the same question to an agent that already has it in this turn's plan
        if any(s["agent"] == target and s["question"] == step["question"] for s in plan):
            return None, ""
        return target, reason

    def _synthesize(self, state: MultiAgentState) -> Dict[str, Any]:
        """Combine the answers of several steps into one answer.

        The combined text is checked against the partial answers by the grader; if it adds or changes anything,
        the partial answers are shown one after another instead (they were each checked by their own agent).
        """
        effective = _effective_results(state)
        question = state.get("question", "")
        language = response_language(question, state.get("chat_history", []))
        parts = [{"agent": r["display_name"], "question": r["question"], "answer": r["answer"]} for r in effective]
        fallback = "\n\n".join(f"**{r['display_name']}**\n\n{r['answer']}" for r in effective)
        synthesis_grade = ""
        try:
            response = self.chat_model.invoke(build_synthesis_messages(question, parts, language))
            answer = response.content.strip() or fallback
            status = "success"
        except Exception as e:
            logger.error(f"[Orchestrator] Answer synthesis failed, showing the partial answers: {e}")
            answer, status = fallback, "error"
        if answer != fallback:
            partial_answers = "\n\n".join(f"[{p['agent']}] {p['answer']}" for p in parts)
            try:
                synthesis_grade = self.grader_model.invoke(
                    build_grader_messages(partial_answers, question, answer)
                ).content.strip()
            except Exception as e:
                logger.error(f"[Orchestrator] Could not check the combined answer: {e}")
                synthesis_grade = "no (grader unavailable)"
            if not is_grade_passed(synthesis_grade):
                logger.warning(
                    "[Orchestrator] Combined answer not supported by the partial answers; showing them as is."
                )
                answer, status = fallback, "unverified"

        sources, seen = [], set()
        for r in effective:
            for source in r["sources"]:
                key = (source.get("source"), source.get("chunk_index"), source.get("content"))
                if key not in seen:
                    seen.add(key)
                    sources.append(source)

        # The combined answer counts as verified only if every graded part passed the grounding check
        grades = [r["hallucination_grade"] for r in effective if r.get("hallucination_grade")]
        failed = [g for g in grades if not is_grade_passed(g)]
        grade = failed[0] if failed else ("yes" if grades else "")

        trace = list(state.get("agent_trace", [])) + [
            {
                "agent": "supervisor",
                "display_name": SUPERVISOR_DISPLAY_NAME,
                "action": "synthesize",
                "combined_agents": [r["agent"] for r in effective],
                "hallucination_grade": synthesis_grade,
                "duration_ms": 0,
                "status": status,
                "timestamp": _now(),
            }
        ]
        return {
            "final_answer": answer,
            "sources": sources,
            "agent_trace": trace,
            "hallucination_grade": grade,
            "is_refined": any(r.get("is_refined") for r in effective),
        }

    def _build_graph(self, checkpointer=None):
        """Compile the dynamic LangGraph StateGraph with Supervisor routing and registered worker nodes."""
        workflow = StateGraph(MultiAgentState)

        workflow.add_node("supervisor", self.supervisor.route)
        workflow.set_entry_point("supervisor")
        workflow.add_node(SYNTHESIZE_NODE, self._synthesize)
        workflow.add_node(RECORD_TURN_NODE, self._record_turn)
        workflow.add_edge(SYNTHESIZE_NODE, RECORD_TURN_NODE)
        workflow.add_edge(RECORD_TURN_NODE, END)

        registered_agents = self.registry.list_agents()
        agent_names = [agent.name for agent in registered_agents]

        def next_node(state: MultiAgentState) -> str:
            plan = state.get("plan") or []
            index = state.get("plan_index", 0)
            if index < len(plan) and plan[index]["agent"] in agent_names:
                return plan[index]["agent"]
            if len(_effective_results(state)) > 1:
                return SYNTHESIZE_NODE
            return RECORD_TURN_NODE

        edge_mapping = {name: name for name in agent_names}
        edge_mapping[SYNTHESIZE_NODE] = SYNTHESIZE_NODE
        edge_mapping[RECORD_TURN_NODE] = RECORD_TURN_NODE

        for agent in registered_agents:
            # Inject the shared models into sub-agents that were created without one
            if agent._chat_model is None:
                agent.chat_model = self.chat_model
            if getattr(agent, "_grader_model", False) is None:
                agent.grader_model = self.grader_model
            workflow.add_node(agent.name, self._make_step_node(agent))
            workflow.add_conditional_edges(agent.name, next_node, edge_mapping)

        workflow.add_conditional_edges("supervisor", next_node, edge_mapping)

        app = workflow.compile(checkpointer=checkpointer) if checkpointer else workflow.compile()
        logger.info(f"[Orchestrator] Compiled MultiAgent workflow with {len(agent_names)} sub-agents: {agent_names}")
        return app

    # ──────────────────────────── EXECUTION ────────────────────────────

    @staticmethod
    def _turn_input(
        question: str, forced_agent: Optional[str], user: Optional[Dict[str, Any]], has_session: bool = False
    ) -> MultiAgentState:
        """Per-turn input. Every non-persistent key is reset so values never leak from the previous turn.

        chat_history and pending_request are left out on purpose: the checkpointer carries them between turns.
        """
        return {
            "question": question,
            "forced_agent": forced_agent,
            "user": dict(user or {}),
            "has_session": has_session,
            "next_agent": "",
            "plan": [],
            "plan_index": 0,
            "step_results": [],
            "handoff_count": 0,
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
            # Every agent whose answer is part of the final answer (several for composite questions)
            "agents": [r["agent"] for r in _effective_results(state)],
            "hallucination_grade": state.get("hallucination_grade", ""),
            "is_refined": state.get("is_refined", False),
            "chat_history": state.get("chat_history", []),
        }

    def query(
        self,
        question: str,
        thread_id: Optional[str] = None,
        forced_agent: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the multi-agent workflow and return verified answer, sources, and agent trace.

        user: {"username", "role", "groups"} of the asking user (document access, service requests).
        """
        app, config = self._app_and_config(thread_id)
        result = app.invoke(self._turn_input(question, forced_agent, user, bool(thread_id)), config=config)
        return self._to_result(result)

    def _step_events(self, step: Dict[str, Any]) -> List[Dict[str, Any]]:
        sub_agent = self.registry.get(step["agent"])
        display_name = (sub_agent.display_name if sub_agent else "") or step["agent"]
        if step.get("handoff_from"):
            reason = f"Handed over from '{step['handoff_from']}' to specialist '{display_name}'."
        else:
            reason = f"Task delegated to specialist: '{display_name}'."
        return [
            {"type": "agent_selected", "agent": step["agent"], "display_name": display_name, "reason": reason},
            {"type": "status", "message": f"🤖 {display_name}: Executing specialized task...", "node": step["agent"]},
        ]

    def stream_events(
        self,
        question: str,
        thread_id: Optional[str] = None,
        forced_agent: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
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

        for mode, chunk in app.stream(
            self._turn_input(question, forced_agent, user, bool(thread_id)),
            config=config,
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom":
                # Progress reported by an agent while it works (BaseSubAgent.report_progress)
                if isinstance(chunk, dict) and chunk.get("type") == "progress":
                    yield chunk
                continue
            for node, update in chunk.items():
                update = update or {}
                final_state.update(update)

                if node == "supervisor":
                    plan = update.get("plan") or []
                    if not plan:
                        yield {
                            "type": "agent_selected",
                            "agent": "supervisor",
                            "display_name": SUPERVISOR_DISPLAY_NAME,
                            "reason": "General query or greeting handled directly by Supervisor.",
                        }
                        continue
                    if len(plan) > 1:
                        yield {
                            "type": "plan",
                            "steps": [{"agent": s["agent"], "question": s["question"]} for s in plan],
                        }
                    yield from self._step_events(plan[0])
                elif node == SYNTHESIZE_NODE:
                    yield {"type": "sources", "sources": update.get("sources", [])}
                elif node != RECORD_TURN_NODE:
                    yield {"type": "sources", "sources": update.get("sources", [])}
                    trace = update.get("agent_trace") or []
                    if trace and trace[-1].get("action") == "handoff":
                        yield {
                            "type": "handoff",
                            "from": trace[-1]["from_agent"],
                            "to": trace[-1]["target_agent"],
                            "reason": trace[-1]["reason"],
                        }
                    plan = update.get("plan") or []
                    index = update.get("plan_index", len(plan))
                    if index < len(plan):
                        yield from self._step_events(plan[index])
                    elif len(_effective_results(update)) > 1:
                        yield {
                            "type": "status",
                            "message": "👑 Supervisor: Combining the specialists' answers...",
                            "node": SYNTHESIZE_NODE,
                        }

        result = self._to_result(final_state)
        yield {
            "type": "done",
            "answer": result["answer"],
            "sources": result["sources"],
            "agent_trace": result["agent_trace"],
            "active_agent": result["active_agent"],
            "agents": result["agents"],
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
