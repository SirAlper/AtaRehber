import inspect
from typing import Dict, List, Optional, Type, Union
from src.agent.multi_agent.base import BaseSubAgent
from src.core.logger import get_logger

logger = get_logger("MultiAgent.Registry")


class AgentRegistry:
    """Central registry managing the lifecycle, discovery, and lookup of specialized sub-agents."""

    def __init__(self):
        self._agents: Dict[str, BaseSubAgent] = {}
        # Incremented on every change so compiled workflows can detect that they are stale
        self._version = 0

    @property
    def version(self) -> int:
        """Monotonic counter of registry changes (register / unregister / clear)."""
        return self._version

    def register(self, agent: Union[BaseSubAgent, Type[BaseSubAgent]]) -> BaseSubAgent:
        """Register a sub-agent instance or class in the registry.

        Args:
            agent: Either an instantiated BaseSubAgent or an uninstantiated class.

        Returns:
            The registered BaseSubAgent instance.
        """
        if inspect.isclass(agent):
            instance = agent()
        else:
            instance = agent

        if not isinstance(instance, BaseSubAgent):
            raise TypeError(f"Agent must inherit from BaseSubAgent, got: {type(instance)}")

        if not instance.name:
            raise ValueError("Agent must have a non-empty 'name' attribute.")

        if not instance.description:
            logger.warning(f"Agent '{instance.name}' has an empty 'description'. Routing accuracy may be impaired.")

        if instance.name in self._agents:
            logger.info(f"Overwriting existing agent registration for '{instance.name}'")

        self._agents[instance.name] = instance
        self._version += 1
        logger.info(f"Successfully registered sub-agent: '{instance.name}' ({instance.display_name or instance.name})")
        return instance

    def unregister(self, name: str) -> bool:
        """Remove a registered agent by name."""
        if name in self._agents:
            del self._agents[name]
            self._version += 1
            logger.info(f"Unregistered agent: '{name}'")
            return True
        return False

    def get(self, name: str) -> Optional[BaseSubAgent]:
        """Retrieve a registered agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> List[BaseSubAgent]:
        """Return list of all registered agent instances."""
        return list(self._agents.values())

    def list_agent_names(self) -> List[str]:
        """Return list of all registered agent names."""
        return list(self._agents.keys())

    def get_supervisor_prompt(self) -> str:
        """Generate formatted agent descriptions for the Supervisor prompt.

        Returns a string listing each registered agent with its routing description:
            - **doc_agent**: Searches company policies, PDFs, and operational documentation.
            - **db_agent**: Executes read-only SQL queries on relational databases.
        """
        if not self._agents:
            return "No specialized agents registered."

        lines = []
        for name, agent in self._agents.items():
            desc = agent.description.strip() if agent.description else "No description provided."
            display = f" ({agent.display_name})" if agent.display_name else ""
            lines.append(f"- **`{name}`**{display}: {desc}")

        return "\n".join(lines)

    def clear(self):
        """Clear all registered agents (primarily for test teardown)."""
        self._agents.clear()
        self._version += 1


# Global Singleton Registry Instance
agent_registry = AgentRegistry()


def register_agent(cls: Type[BaseSubAgent]):
    """Class decorator to automatically register a sub-agent with the singleton registry.

    Usage:
        @register_agent
        class MyCustomAgent(BaseSubAgent):
            name = "my_agent"
            description = "Handles specific domain tasks"
            ...
    """
    agent_registry.register(cls)
    return cls
