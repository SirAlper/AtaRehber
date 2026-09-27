from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from src.auth.document_access import allowed_groups_for
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Base")


class BaseSubAgent(ABC):
    """Abstract base class that all specialized sub-agents must inherit from.

    Collaboration hooks used by the orchestrator:
    - is_available(): unavailable agents are hidden from the supervisor (e.g. no database connected).
    - handoff_on: when a run ends with one of these trace statuses, the task is handed to the mapped agent,
      e.g. {"rejected": "doc_agent"}. An agent can also request a handoff explicitly by returning
      {"handoff": {"to": "<agent>", "reason": "..."}}.
    - search_groups(state): document access groups to pass to RAGEngine.search().
    """

    name: str = ""
    display_name: str = ""
    description: str = ""
    handoff_on: Dict[str, str] = {}

    def __init__(self, chat_model=None):
        self._chat_model = chat_model

    @property
    def chat_model(self):
        if self._chat_model is None:
            from src.agent.llm import create_chat_model

            self._chat_model = create_chat_model()
        return self._chat_model

    @chat_model.setter
    def chat_model(self, value):
        self._chat_model = value

    @abstractmethod
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the sub-agent's specialized workflow.

        Args:
            state: The current MultiAgentState dictionary.

        Returns:
            Dictionary with state updates (e.g. {'final_answer': ..., 'sources': ...}).
        """
        pass

    def get_routing_context(self) -> str:
        """Optional live context for the supervisor, e.g. which data this agent can reach.

        Appended to the agent's description in the routing prompt. It is requested for every routed
        question, so keep it short and cheap (cache it if it needs I/O).
        """
        return ""

    def is_available(self) -> bool:
        """Whether the agent can currently do its job; unavailable agents are not offered to the supervisor."""
        return True

    @staticmethod
    def search_groups(state: Dict[str, Any]) -> Optional[List[str]]:
        """Document access groups of the asking user for RAGEngine.search(); None searches every document.

        Requests without a user (internal calls, evaluations) are not filtered; the API always sets the user.
        """
        user = state.get("user")
        if not user:
            return None
        return allowed_groups_for(user.get("role"), user.get("groups"))

    def get_info(self) -> Dict[str, str]:
        """Return agent metadata card for supervisor routing and observability."""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<SubAgent: {self.name} ({self.display_name or self.name})>"
