from typing import Generator, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from src.agent.nodes import AgentNodes
from src.agent.prompts import NO_CONTEXT_RESPONSE


class QueryService:
    """Service managing batch queries and event-based execution flows for the RAG Agent."""

    def __init__(self, app, nodes: AgentNodes, chat_model: BaseChatModel):
        self.app = app
        self.nodes = nodes
        self.chat_model = chat_model

    def query(self, question: str, thread_id: Optional[str] = None) -> dict:
        """Run the LangGraph workflow and return the verified answer, sources, and audit status."""
        config = {"configurable": {"thread_id": thread_id}} if thread_id else {}
        initial_input = {
            "question": question,
            "context": "",
            "sources": [],
            "answer": "",
            "hallucination_grade": "",
            "retry_count": 0,
            "is_refined": False,
        }
        if not thread_id:
            initial_input["chat_history"] = []

        result = self.app.invoke(initial_input, config=config)
        return {
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "hallucination_grade": result.get("hallucination_grade", ""),
            "is_refined": result.get("is_refined", False),
            "chat_history": result.get("chat_history", []),
        }

    def stream_events(self, question: str, thread_id: Optional[str] = None) -> Generator[dict, None, None]:
        """Yield workflow stage events and deliver the final answer upon completion."""
        prior_history = []
        if thread_id and hasattr(self.app, "get_state"):
            try:
                graph_state = self.app.get_state({"configurable": {"thread_id": thread_id}})
                if graph_state and graph_state.values:
                    prior_history = list(graph_state.values.get("chat_history", []))
            except Exception:
                pass

        state = {
            "question": question,
            "context": "",
            "sources": [],
            "answer": "",
            "hallucination_grade": "",
            "retry_count": 0,
            "is_refined": False,
            "chat_history": prior_history,
        }

        # 1. REWRITE (Dynamic Query Optimization)
        yield {
            "type": "status",
            "message": "🔄 Optimizing search query...",
            "node": "rewrite",
        }
        rewrite_out = self.nodes.rewrite_query(state)
        state["search_query"] = rewrite_out.get("search_query", state["question"])

        # 2. RETRIEVE
        yield {
            "type": "status",
            "message": "🔍 Searching relevant enterprise documents...",
            "node": "retrieve",
        }
        retrieve_out = self.nodes.retrieve(state)
        state["context"] = retrieve_out["context"]
        state["sources"] = retrieve_out["sources"]
        yield {"type": "sources", "sources": state["sources"]}

        context = state["context"].strip()
        if not context:
            yield {
                "type": "done",
                "answer": NO_CONTEXT_RESPONSE,
                "sources": [],
                "is_refined": False,
            }
            return

        # 3. GENERATE
        yield {
            "type": "status",
            "message": "✍️ Preparing response...",
            "node": "generate",
        }
        generate_out = self.nodes.generate(state)
        state["answer"] = generate_out["answer"]
        state["chat_history"] = generate_out.get("chat_history", state["chat_history"])

        # 4. GRADE & REFINE LOOP
        while True:
            yield {
                "type": "status",
                "message": "🛡️ Verifying factual accuracy...",
                "node": "grade",
            }
            grade_out = self.nodes.grade_hallucination(state)
            state["hallucination_grade"] = grade_out["hallucination_grade"]

            decision = self.nodes.decide_hallucinate(state)
            if decision == "refine":
                yield {
                    "type": "status",
                    "message": "✍️ Re-evaluating and refining response to match documents...",
                    "node": "refine",
                }
                refine_out = self.nodes.refine(state)
                state["answer"] = refine_out["answer"]
                state["is_refined"] = True
                state["retry_count"] = refine_out.get("retry_count", state.get("retry_count", 0) + 1)
                continue
            elif decision == "fallback":
                yield {
                    "type": "warning",
                    "message": "⚠️ Generated response could not be fully verified against company documents.",
                    "node": "fallback",
                }
                fallback_out = self.nodes.fallback(state)
                state["answer"] = fallback_out["answer"]
                yield {
                    "type": "grade",
                    "grade": state["hallucination_grade"],
                    "passed": False,
                    "is_refined": state.get("is_refined", False),
                }
                break
            else:
                yield {
                    "type": "grade",
                    "grade": state["hallucination_grade"],
                    "passed": True,
                    "is_refined": state.get("is_refined", False),
                }
                break

        yield {
            "type": "done",
            "answer": state["answer"],
            "sources": state["sources"],
            "is_refined": state.get("is_refined", False),
        }

    def stream_query(self, question: str, thread_id: Optional[str] = None) -> Generator[str, None, None]:
        """Yield final answer upon workflow completion."""
        for event in self.stream_events(question, thread_id=thread_id):
            if event["type"] == "done":
                yield event["answer"]
