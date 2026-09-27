# 🤖 Custom Sub-Agent Development Guide

`OpenLocalEnterpriseRag` features a **modular, extensible, and pluggable Multi-Agent architecture** designed to incorporate specialized domain sub-agents according to enterprise requirements.

The system is centered around an **Intelligent Supervisor Orchestrator**. Whenever a new sub-agent is registered, the Supervisor **automatically discovers it**, registers its specialization domain, and delegates relevant incoming user inquiries accordingly.

---

## 🏗️ Architectural Overview: How It Works

```text
                     ┌────────────────────────────────────────┐
                     │    👑 Supervisor Orchestrator Router   │
                     │  - Analyzes user intent & semantics    │
                     │  - Reads dynamic registered agent meta │
                     └───────────────────┬────────────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
┌──────────────┐                 ┌──────────────┐                 ┌──────────────────────┐
│  doc_agent   │                 │   db_agent   │                 │ ✨ YOUR CUSTOM AGENT  │
│ Document RAG │                 │ SQL Database │                 │  (@register_agent)   │
└──────────────┘                 └──────────────┘                 └──────────────────────┘
```

Every sub-agent inherits from the standardized `BaseSubAgent` class conforming to LangGraph node conventions and implements an `execute(state)` lifecycle method.

---

## 🚀 Creating a New Agent in 3 Simple Steps

Adding a new specialist sub-agent requires only **3 steps**:

### Step 1: Inherit from `BaseSubAgent`
Define your agent's unique identifier (`name`), UI label (`display_name`), and the **specialization description (`description`)** that the Supervisor uses for intent routing.

### Step 2: Decorate with `@register_agent`
Add `@register_agent` to your class definition to automatically register it into the central `agent_registry`.

### Step 3: Implement the `execute(state)` Method
Write your domain business logic, query execution, or calculations, and return a standardized dictionary containing `{"final_answer": "...", "sources": [...], "agent_trace": [...]}`.

---

## 📦 The `execute(state)` Contract

`execute()` runs as a LangGraph node. It receives the current `MultiAgentState` and returns only the keys it wants to update.

**Keys your agent can read:**

| Key | Description |
| :--- | :--- |
| `question` | The user's current question. |
| `chat_history` | Previous turns of this session: `[{"question": ..., "answer": ..., "agent": ...}, ...]` (empty for the first turn or session-less requests). Use it to resolve follow-ups such as *"and last month?"*. |
| `agent_trace` | Trace entries recorded so far this turn (the supervisor's routing entry). |

**Keys your agent should return:**

| Key | Required | Description |
| :--- | :---: | :--- |
| `final_answer` | ✅ | The answer shown to the user. |
| `sources` | ✅ | Citation dictionaries (`source`, `chunk_index`, `content`, …); `[]` if none. |
| `agent_trace` | ✅ | The incoming `agent_trace` **plus** your own entry (the list is replaced, not merged). |
| `hallucination_grade`, `is_refined` | Optional | Set these if your agent verifies grounding (as `doc_agent` does). |

Do not write `chat_history`: the workflow's `record_turn` step appends the turn after your agent returns. Any new state key must also be declared in `MultiAgentState` (`src/agent/multi_agent/state.py`), because LangGraph silently drops undeclared keys.

---

## 📝 Reference Example: Financial & Currency Calculator (`FinanceCalculatorAgent`)

Below is a complete, production-ready custom agent for financial calculations and currency conversions:

```python
import time
from datetime import datetime, timezone
from typing import Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import register_agent
from src.core.logger import get_logger

logger = get_logger("MultiAgent.FinanceAgent")


@register_agent
class FinanceCalculatorAgent(BaseSubAgent):
    """Specialist sub-agent for financial calculations, currency conversions, and budget metrics."""

    # 1. Unique agent identifier (used for routing)
    name: str = "finance_agent"

    # 2. UI and logging display label
    display_name: str = "Finance & Currency Analyst"

    # 3. CRITICAL: The Supervisor inspects this description to route user questions!
    description: str = (
        "Used for foreign currency exchange rates, currency conversions (USD, EUR, GBP), "
        "VAT/tax calculations, budget ratios, interest calculations, and financial mathematics."
    )

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute domain calculation and grounded response generation."""
        start_time = time.time()
        question = state.get("question", "").strip()
        # Previous turns of this session, for follow-up questions
        history = state.get("chat_history", [])[-3:]

        logger.info(f"[{self.name}] Processing financial request: '{question}'")

        system_prompt = (
            "You are an enterprise financial analyst assistant. "
            "Explain and calculate the user's financial or currency request step-by-step. "
            "Present results clearly with professional formatting."
        )

        try:
            # self.chat_model automatically reuses the shared local LLM backend
            history_text = "\n".join(f"User: {t['question']}\nAssistant: {t['answer']}" for t in history)
            response = self.chat_model.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"{history_text}\n\nCurrent question: {question}" if history_text else question),
            ])
            answer = response.content.strip()
            status = "success"
        except Exception as e:
            # Log details server-side; never return exception text to the user
            logger.error(f"[{self.name}] Calculation error: {e}")
            answer = "An error occurred while processing the financial request. Please try again later."
            status = "error"

        duration_ms = int((time.time() - start_time) * 1000)

        # Transparent execution trace entry
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "financial_calculation",
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Standardized return contract
        return {
            "final_answer": answer,
            "sources": [{
                "source": "FinanceEngine: Calculator",
                "chunk_index": 0,
                "content": "Enterprise financial calculation engine output.",
            }],
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }
```

---

## ⚙️ Registration Options

You can register sub-agents in two ways:

### Method A: Decorator Registration (Recommended)
Add `@register_agent` above your class and save the file in `src/agent/multi_agent/sub_agents/`:
```python
# src/agent/multi_agent/sub_agents/finance_agent.py
@register_agent
class FinanceCalculatorAgent(BaseSubAgent):
    ...
```

The decorator registers the agent when its module is **imported**, so also import it in `src/agent/multi_agent/sub_agents/__init__.py` (which the orchestrator imports at startup):
```python
from src.agent.multi_agent.sub_agents.finance_agent import FinanceCalculatorAgent
```
Without this import the file is never loaded and the agent does not appear in `GET /api/v1/agents`.

### Method B: Programmatic Runtime Registration
To dynamically register or unregister an agent at runtime. The orchestrator detects registry changes and recompiles its workflow on the next query; existing conversation sessions are preserved.
```python
from src.agent.multi_agent.registry import agent_registry

# Register agent instance
agent = MyCustomAgent()
agent_registry.register(agent)

# List registered agents
print(agent_registry.list_agent_names())
# Output: ['doc_agent', 'db_agent', 'compliance_agent', 'my_custom_agent']

# Unregister if needed
agent_registry.unregister("my_custom_agent")
```

---

## 💡 Best Practices

1. **`description` Field is Paramount:**
   * The Supervisor routes queries **strictly based on this semantic description**.
   * Include clear keywords and task types your agent handles.
   * *Avoid:* `"Handles financial tasks."`
   * *Recommended:* `"Used for foreign currency exchange rates, currency conversions (USD, EUR, GBP), VAT/tax calculations, budget ratios, and cost analyses."`

   * If routing depends on live data (for example which tables or systems your agent can reach), override `get_routing_context()` to return a short sentence. The supervisor appends it to your description on every routed question, so cache anything that needs I/O. `db_agent` uses this to list the connected tables; without it, small models sent every database question to `doc_agent`.

2. **Memory Safety & Lazy Loading:**
   * If your agent requires heavy dependencies or external drivers, load them inside `execute()` or behind a cached `@property` rather than during module import.
   * Leave `chat_model` unset: the orchestrator injects the shared LLM instance, preventing duplicate VRAM allocations. Pass `chat_model=` only in tests.

3. **Use the Conversation History:**
   * `state["chat_history"]` holds the session's previous turns. Include the last few in your prompt so follow-up questions resolve correctly.

4. **Transparent Auditing (`agent_trace`):**
   * Always append an `agent_trace` entry in the dictionary returned by `execute()`. This feeds the Streamlit UI trace panel and the audit database.

5. **Graceful Degradation:**
   * Wrap external API or database calls in `try-except` blocks. If an error occurs, return a helpful, generic message with `status: "error"` in the trace entry without crashing the pipeline. Log the exception details; do not put them in `final_answer`, which is shown to users and stored in the audit log.

6. **Database Access:**
   * Query databases through `DatabaseConnector.execute_query()` (or the `sql_db_query` tool) so the read-only guard applies. Get the shared connector with `src.api.state.get_db_connector()`.

---

## 🧪 Testing Your Custom Agent

You can test custom sub-agents using standard `unittest` or `pytest`. Pass a mock `chat_model` so no LLM is loaded:

```python
import unittest
from unittest.mock import MagicMock
from src.agent.multi_agent.registry import AgentRegistry
from my_custom_agent import FinanceCalculatorAgent

class TestFinanceAgent(unittest.TestCase):
    def test_finance_agent_execution(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="100 USD = 3450 TRY")

        agent = FinanceCalculatorAgent(chat_model=mock_llm)
        result = agent.execute({"question": "Convert 100 USD to local currency", "chat_history": []})

        self.assertIn("3450 TRY", result["final_answer"])
        self.assertEqual(len(result["agent_trace"]), 1)
        self.assertEqual(result["agent_trace"][0]["agent"], "finance_agent")

if __name__ == "__main__":
    unittest.main()
```

To test routing and memory end to end, build a `MultiAgentOrchestrator` with your own `AgentRegistry`, a mock chat model, and a `MemorySaver` checkpointer. See `tests/test_orchestrator_e2e.py` for examples.
