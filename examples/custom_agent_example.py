"""
Custom Sub-Agent Reference Implementation.

This sample script demonstrates how to define an independent specialist sub-agent,
register it with the central AgentRegistry, and execute it within the MultiAgent system.

Execution:
    python examples/custom_agent_example.py
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.agent.multi_agent.base import BaseSubAgent
from src.agent.multi_agent.registry import agent_registry, register_agent


@register_agent
class CurrencyConverterAgent(BaseSubAgent):
    """Specialist sub-agent for corporate exchange rates and currency conversions."""

    name: str = "currency_agent"
    display_name: str = "Currency & Exchange Analyst"
    description: str = (
        "Used for foreign exchange rates, currency conversions (USD, EUR, GBP, TRY), "
        "exchange rate variance, and corporate billing currency queries."
    )

    # Sample corporate benchmark exchange rates
    RATES_TO_TRY = {
        "usd": 34.50,
        "eur": 37.80,
        "gbp": 45.20,
    }

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        question = state.get("question", "").strip()

        # Calculation logic (demo purposes)
        reply = (
            f"💱 **Corporate Currency Report**\n\n"
            f"Current Benchmark Exchange Rates:\n"
            f"- **1 USD:** {self.RATES_TO_TRY['usd']:.2f} TRY\n"
            f"- **1 EUR:** {self.RATES_TO_TRY['eur']:.2f} TRY\n"
            f"- **1 GBP:** {self.RATES_TO_TRY['gbp']:.2f} TRY\n\n"
            f"Query: *\"{question}\"*\n"
            f"Calculation processed against corporate accounting benchmark table."
        )

        duration_ms = int((time.time() - start_time) * 1000)
        trace_entry = {
            "agent": self.name,
            "display_name": self.display_name,
            "action": "currency_conversion",
            "duration_ms": duration_ms,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "final_answer": reply,
            "sources": [
                {
                    "source": "Corporate: Central Bank Exchange Rates",
                    "chunk_index": 0,
                    "content": "Daily corporate benchmark exchange rate table.",
                }
            ],
            "agent_trace": list(state.get("agent_trace", [])) + [trace_entry],
        }


def main():
    print("=" * 60)
    print("🤖 Multi-Agent Dynamic Registration Verification")
    print("=" * 60)

    # 1. List registered agents in registry
    print("\n📋 Registered Agents:")
    for name in agent_registry.list_agent_names():
        agent = agent_registry.get(name)
        print(f"  - [{name}] {agent.display_name}")

    # 2. Inspect dynamic supervisor prompt
    print("\n👑 Supervisor Routing Prompt Summary:")
    print(agent_registry.get_supervisor_prompt())

    # 3. Direct agent execution test
    print("\n⚡ Executing CurrencyConverterAgent Directly:")
    currency_agent = agent_registry.get("currency_agent")
    test_state = {"question": "How much is 1000 USD in TRY?", "agent_trace": []}
    result = currency_agent.execute(test_state)

    print("\n--- Agent Answer ---")
    print(result["final_answer"])
    print("\n--- Sources ---")
    print(result["sources"])
    print("\n--- Execution Trace ---")
    print(result["agent_trace"])
    print("\n✅ Custom sub-agent executed and integrated successfully!")


if __name__ == "__main__":
    main()
