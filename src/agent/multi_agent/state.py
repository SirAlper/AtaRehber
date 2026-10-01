from typing import Any, Dict, List, Optional, TypedDict


class MultiAgentState(TypedDict, total=False):
    """Central state container shared across the LangGraph Multi-Agent workflow.

    LangGraph only carries keys declared here: anything else passed to invoke() is dropped.
    chat_history, pending_request, and pending_clarification are persisted across turns by the checkpointer; all
    other keys are reset per turn.
    """

    question: str  # Original user query
    forced_agent: Optional[str]  # Explicit sub-agent selected by the user (bypasses routing)
    user: Dict[str, Any]  # Asking user: username, role, groups (document access, service requests)
    has_session: bool  # True when the turn belongs to a persisted conversation (a follow-up message is possible)
    chat_history: List[Dict[str, str]]  # Prior conversation turns (persisted per thread)
    pending_request: Optional[Dict[str, Any]]  # Drafted service request awaiting the user's yes/no (persisted)
    # Question the supervisor asked back, {"question": <the original question>}; the next message answers it (persisted)
    pending_clarification: Optional[Dict[str, Any]]
    clarification: Dict[str, Any]  # This turn's question back: {"question", "options"}; empty when none was asked
    clarified: bool  # This turn answers a question back: agents must not ask again
    next_agent: str  # Routing decision made by the Supervisor (first planned agent)
    # Agent steps to run: {"agent", "question", "id", "uses": [ids of earlier steps it needs], "handoff_from"?}
    plan: List[Dict[str, Any]]
    plan_index: int  # Index of the next step to run
    step_results: List[Dict[str, Any]]  # One entry per executed step (answer, sources, status, step_id)
    handoff_count: int  # Handoffs used this turn (limited by MAX_AGENT_HANDOFFS)
    active_agent: str  # Agent that produced the final answer this turn ("multi_agent" for combined answers)
    agent_trace: List[Dict[str, Any]]  # Chronological execution trace (which agent ran, runtime, result preview)
    final_answer: str  # Consolidated final answer delivered to user
    sources: List[Dict[str, Any]]  # Consolidated list of sources from all contributing agents
    hallucination_grade: str  # Grounding verdict from Self-RAG capable agents
    is_refined: bool  # Whether the answer was pruned by the refine step
    # Outcome of the answer check: {"level": "verified" | "partial" | "unverified", "issues": [...]}; empty when the
    # answer was not checked (greetings, database answers, compliance reports, requests)
    verification: Dict[str, Any]
