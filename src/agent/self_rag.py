"""Self-RAG guard shared by doc_agent and custom agents: grade an answer against its context, refine it once."""

from src.agent.grading import GRADE_UNAVAILABLE, grade_from_quotes, verified_quotes
from src.agent.llm import json_mode
from src.agent.prompts import build_grader_messages, build_quote_grader_messages, build_refine_messages
from src.core import config
from src.core.logger import get_logger

logger = get_logger("SelfRAG")


def grade_answer_with_quotes(grader_model, context: str, question: str, answer: str, agent_name: str = "") -> tuple:
    """(grade, quotes): whether the answer is supported by the context, and the grader's quotes that really occur
    in it (empty with GRADER_MODE=simple). Fails closed on errors.

    With GRADER_MODE=quotes the grader must back each fact with a sentence copied from the context, and the
    copies are checked here; a made-up quote fails the answer even if the grader says 'yes'.
    """
    try:
        if config.GRADER_MODE == "quotes":
            messages = build_quote_grader_messages(context, question, answer)
            try:
                response = json_mode(grader_model).invoke(messages)
            except Exception as e:
                # In JSON mode the model sometimes repeats a token until Ollama aborts ("token repeat limit
                # reached"); the verdict is also read from plain text
                logger.warning(f"[{agent_name}] JSON grading failed ({e}), retrying without JSON mode.")
                response = grader_model.invoke(messages)
            grade = grade_from_quotes(response.content, context, answer=answer, question=question)
            return grade, verified_quotes(response.content, context)
        response = grader_model.invoke(build_grader_messages(context, question, answer))
        return response.content.strip(), []
    except Exception as e:
        logger.error(f"[{agent_name}] Grading error, treating answer as unverified: {e}")
        return GRADE_UNAVAILABLE, []


def grade_answer(grader_model, context: str, question: str, answer: str, agent_name: str = "") -> str:
    """Whether the answer is supported by the context (see grade_answer_with_quotes)."""
    return grade_answer_with_quotes(grader_model, context, question, answer, agent_name)[0]


def refine_answer(
    chat_model, context: str, question: str, draft_answer: str, language: str, objection: str = "", agent_name: str = ""
) -> str:
    """Prune claims from the draft that the context does not support (the grader's objection first)."""
    try:
        messages = build_refine_messages(context, question, draft_answer, language, objection=objection)
        response = chat_model.invoke(messages)
        return response.content.strip() or draft_answer
    except Exception as e:
        logger.error(f"[{agent_name}] Refinement error, keeping draft: {e}")
        return draft_answer
