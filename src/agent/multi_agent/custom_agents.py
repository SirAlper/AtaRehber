"""Agents defined by admins in the web UI: a name, what they are for, instructions, and tools.

A custom agent is stored in CUSTOM_AGENTS_FILE and registered with the agent registry like a built-in one, so the
supervisor routes questions to it by its description and the orchestrator recompiles the workflow. The model
decides which of the agent's tools to call (Ollama tool calling). Answers that use the documents pass the same
quote-based check as doc_agent, with every tool result as context, so the instructions cannot switch off the
grounding rules.
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field, field_validator

from src.agent.grading import grade_objection, is_grade_passed
from src.agent.language import language_instruction, message, response_language
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import AgentRegistry, agent_registry
from src.agent.multi_agent.tools import TOOLS, ToolRun, available_tools, build_tools
from src.agent.prompts import ORGANIZATION
from src.agent.self_rag import grade_answer, refine_answer
from src.core.config import CUSTOM_AGENTS_FILE
from src.core.logger import get_logger

logger = get_logger("MultiAgent.CustomAgents")

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
# Names of workflow nodes and routing keywords; built-in agents are added at validation time
RESERVED_NAMES = {"supervisor", "auto", "none", "finish", "multi_agent", "synthesize", "record_turn", "error"}
MAX_CUSTOM_AGENTS = 20
# Model calls with tool results before the agent must answer
MAX_TOOL_ROUNDS = 4


class CustomAgentConfig(BaseModel):
    name: str = Field(..., description="System name: 3-40 lowercase letters, digits, underscores, e.g. aof_asistani")
    display_name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(
        ..., min_length=10, max_length=500, description="What the agent is for; the supervisor routes by this text"
    )
    instructions: str = Field(..., min_length=10, max_length=4000, description="How the agent works (its prompt)")
    tools: List[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        value = value.strip()
        if not NAME_PATTERN.match(value):
            raise ValueError("Use 3-40 lowercase letters, digits, or underscores, starting with a letter.")
        if value in RESERVED_NAMES:
            raise ValueError(f"'{value}' is reserved.")
        return value

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, value: List[str]) -> List[str]:
        unknown = [tool for tool in value if tool not in TOOLS]
        if unknown:
            raise ValueError(f"Unknown tool(s): {', '.join(unknown)}. Available: {', '.join(TOOLS)}.")
        return list(dict.fromkeys(value))

    @field_validator("display_name", "description", "instructions")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class CustomAgentStore:
    """Thread-safe JSON list of custom agent definitions (data directory, so part of full backups)."""

    def __init__(self, file_path: str = CUSTOM_AGENTS_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.file_path):
            return []
        with open(self.file_path, encoding="utf-8") as f:
            return list(json.load(f))

    def _save(self, agents: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        temp_file = f"{self.file_path}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(agents, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.file_path)

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return next((agent for agent in self.all() if agent["name"] == name), None)

    def save(self, agent: CustomAgentConfig, username: str, reserved: set = frozenset()) -> Dict[str, Any]:
        """Create or replace an agent definition; raises ValueError for a taken or reserved name."""
        with self._lock:
            agents = self._load()
            existing = next((a for a in agents if a["name"] == agent.name), None)
            if existing is None and agent.name in reserved:
                raise ValueError(f"'{agent.name}' is the name of a built-in agent.")
            if existing is None and len(agents) >= MAX_CUSTOM_AGENTS:
                raise ValueError(f"At most {MAX_CUSTOM_AGENTS} custom agents.")
            now = datetime.now(timezone.utc).isoformat()
            record = {
                **agent.model_dump(),
                "created_by": existing["created_by"] if existing else username,
                "created_at": existing["created_at"] if existing else now,
                "updated_by": username,
                "updated_at": now,
            }
            agents = [a for a in agents if a["name"] != agent.name] + [record]
            self._save(agents)
            return record

    def delete(self, name: str) -> bool:
        with self._lock:
            agents = self._load()
            remaining = [a for a in agents if a["name"] != name]
            if len(remaining) == len(agents):
                return False
            self._save(remaining)
            return True


custom_agent_store = CustomAgentStore()

SYSTEM_RULES = (
    "You are '{display_name}', a specialist assistant of {organization}.\n"
    "Your task, as defined by the administrator:\n{instructions}\n\n"
    "Rules that always apply:\n"
    "{tool_rules}"
    "- Never invent facts about {organization} (rules, numbers, dates, names, deadlines).\n"
    "- Keep the answer focused on the question; finish every sentence."
)
TOOL_RULES = {
    "documents": (
        "- Facts about the organization must come from search_documents results. If the search finds nothing "
        "relevant, say that the information is not in the documents. Cite the article (e.g. 'Madde 30') when shown."
    ),
    "calculator": "- Use the calculator for arithmetic instead of computing in your head.",
    "dates": "- Use date_calculator for dates and deadlines instead of counting days yourself.",
    "database": "- Use query_database for stored records; only SELECT queries on the listed tables.",
}


class CustomAgent(BaseSubAgent):
    """An agent defined in the web UI (see the module docstring)."""

    def __init__(self, definition: Dict[str, Any], chat_model=None, grader_model=None):
        super().__init__(chat_model=chat_model)
        self.definition = definition
        self.name = definition["name"]
        self.display_name = definition["display_name"]
        self.description = definition["description"]
        self.tools = list(definition.get("tools", []))
        self.enabled = bool(definition.get("enabled", True))
        # Injected by the orchestrator (OLLAMA_GRADER_MODEL) like doc_agent's
        self._grader_model = grader_model

    @property
    def grader_model(self):
        return self._grader_model or self.chat_model

    @grader_model.setter
    def grader_model(self, value):
        self._grader_model = value

    def is_available(self) -> bool:
        # An agent whose only tools cannot work right now (e.g. no database) is hidden from the supervisor
        return self.enabled and (not self.tools or bool(available_tools(self.tools)))

    def get_info(self) -> Dict[str, str]:
        return {**super().get_info(), "custom": True, "tools": self.tools}

    def _system_prompt(self, tools: List[str], language: str) -> str:
        rules = "".join(f"{TOOL_RULES[name]}\n" for name in tools)
        prompt = SYSTEM_RULES.format(
            display_name=self.display_name,
            organization=ORGANIZATION,
            instructions=self.definition["instructions"],
            tool_rules=rules,
        )
        return f"{prompt}\n{language_instruction(language)}"

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()
        chat_history = state.get("chat_history", [])
        language = response_language(question, chat_history)
        tool_names = available_tools(self.tools)
        run = ToolRun()
        tools = build_tools(tool_names, run, state)

        history = [
            f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')}"
            for turn in chat_history[-3:]
            if turn.get("question") and turn.get("answer")
        ]
        user_text = ("Recent conversation:\n" + "\n".join(history) + "\n\n" if history else "") + question
        messages = [SystemMessage(content=self._system_prompt(tool_names, language)), HumanMessage(content=user_text)]

        answer, tools_called, status = self._run(messages, tools)

        grade, is_refined = "", False
        if status == "success" and run.documents_used:
            # Every tool result is context: a computed deadline is then grounded like a quoted rule
            context = run.context()
            if not context:
                answer = message("no_context", language)
            else:
                grader = self.grader_model
                grade = grade_answer(grader, context, question, answer, agent_name=self.name)
                if not is_grade_passed(grade):
                    answer = refine_answer(
                        self.chat_model, context, question, answer, language, grade_objection(grade), self.name
                    )
                    is_refined = True
                    grade = grade_answer(grader, context, question, answer, agent_name=self.name)
                    if not is_grade_passed(grade):
                        answer = message("fallback", language)
        if status != "success":
            answer = message("fallback", language)

        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "custom_agent",
            "tools_called": tools_called,
            "sources_count": len(run.sources),
            "duration_ms": int((time.time() - start_time) * 1000),
            "status": status if not grade or is_grade_passed(grade) else "unverified",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if grade:
            trace_entry["hallucination_grade"] = grade
        result = {
            "final_answer": answer,
            "sources": run.sources,
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
        if grade:
            result.update(hallucination_grade=grade, is_refined=is_refined)
        return result

    def _run(self, messages: list, tools: list) -> tuple:
        """Let the model call tools until it answers: (answer, names of the tools called, status)."""
        tools_called: List[str] = []
        try:
            if not tools:
                return self.chat_model.invoke(messages).content.strip(), tools_called, "success"
            by_name = {tool.name: tool for tool in tools}
            model = self.chat_model.bind_tools(tools)
            for _ in range(MAX_TOOL_ROUNDS):
                response = model.invoke(messages)
                calls = getattr(response, "tool_calls", None) or []
                if not calls:
                    return str(response.content).strip(), tools_called, "success"
                messages.append(AIMessage(content=response.content or "", tool_calls=calls))
                for call in calls:
                    tool = by_name.get(call.get("name"))
                    tools_called.append(call.get("name", "?"))
                    try:
                        output = (
                            tool.invoke(call.get("args") or {}) if tool else f"Error: unknown tool {call.get('name')}"
                        )
                    except Exception as e:
                        logger.warning(f"[{self.name}] Tool '{call.get('name')}' failed: {e}")
                        output = f"Error: {e}"
                    messages.append(ToolMessage(content=str(output), tool_call_id=call.get("id") or call.get("name")))
            # Out of rounds: answer with what the tools returned so far
            messages.append(HumanMessage(content="Answer the question now with the information above."))
            return self.chat_model.invoke(messages).content.strip(), tools_called, "success"
        except Exception as e:
            logger.error(f"[{self.name}] Custom agent failed: {e}")
            return "", tools_called, "error"


def built_in_agent_names(registry: AgentRegistry = agent_registry) -> set:
    return {agent.name for agent in registry.list_agents() if not isinstance(agent, CustomAgent)}


def sync_custom_agents(registry: AgentRegistry = agent_registry, store: CustomAgentStore = custom_agent_store) -> int:
    """Register the stored custom agents and unregister deleted ones; returns the number registered.

    A definition whose name clashes with a built-in agent is skipped, so a stale file cannot replace one.
    """
    try:
        definitions = store.all()
    except Exception as e:
        logger.error(f"Cannot read custom agents from {store.file_path}: {e}")
        return 0
    built_in = built_in_agent_names(registry)
    wanted = {d["name"]: d for d in definitions if d.get("name") and d["name"] not in built_in}
    for agent in registry.list_agents():
        if isinstance(agent, CustomAgent) and agent.name not in wanted:
            registry.unregister(agent.name)
    for name, definition in wanted.items():
        current = registry.get(name)
        if isinstance(current, CustomAgent) and current.definition == definition:
            continue
        registry.register(CustomAgent(definition))
    return len(wanted)
