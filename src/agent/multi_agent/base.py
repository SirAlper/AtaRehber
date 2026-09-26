from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain_core.tools import BaseTool
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Base")


class BaseSubAgent(ABC):
    """Abstract base class that all specialized sub-agents must inherit from."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    tools: List[BaseTool] = []

    def __init__(self, chat_model=None, tools: Optional[List[BaseTool]] = None):
        self._chat_model = chat_model
        if tools is not None:
            self.tools = tools
        elif not hasattr(self, "tools"):
            self.tools = []

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

    def get_info(self) -> Dict[str, str]:
        """Return agent metadata card for supervisor routing and observability."""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<SubAgent: {self.name} ({self.display_name or self.name})>"
