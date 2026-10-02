"""Self-RAG guard shared by doc_agent and custom agents: grade an answer against its context, refine it once."""

from typing import Optional

from src.agent.grading import (
    GRADE_UNAVAILABLE,
    answers_question,
    cited_sentences,
    grade_from_quotes,
    grade_from_sentences,
    number_sentences,
    verified_quotes,
)
from src.agent.language import SUPPORTED_LANGUAGES, foreign_script
from src.agent.llm import json_mode
from src.agent.prompts import build_evidence_grader_messages, build_grader_messages, build_refine_messages
from src.core import config
from src.core.logger import get_logger

logger = get_logger("SelfRAG")


def grade_with_evidence(
    grader_model, context: str, question: str, answer: str, agent_name: str = "", objection: Optional[str] = None
) -> tuple:
    """(grade, quotes, answers the question) from one look of the grader that shows its evidence.

    GRADER_MODE=sentences numbers the sentences of the context and takes the ones the grader points to as the
    quotes; otherwise the grader copies its quotes and the copies are checked (a made-up quote fails the answer
    even if the grader says 'yes'; with GRADER_STRICT_QUOTES=false it is only left out). The third value is the
    grader's "answers_question" with GRADER_RELEVANCE_CHECK, else True.

    objection: the first objection, for a second look at a rejected answer; None for the first look.
    Raises when the model fails in JSON mode and as plain text.
    """
    by_sentences = config.GRADER_MODE == "sentences"
    numbered, sentences = number_sentences(context) if by_sentences else (context, [])
    messages = build_evidence_grader_messages(
        numbered,
        question,
        answer,
        mode="sentences" if by_sentences else "quotes",
        relevance=config.GRADER_RELEVANCE_CHECK,
        objection=objection,
    )
    try:
        response = json_mode(grader_model).invoke(messages)
    except Exception as e:
        # In JSON mode the model sometimes repeats a token until Ollama aborts ("token repeat limit
        # reached"); the verdict is also read from plain text
        logger.warning(f"[{agent_name}] JSON grading failed ({e}), retrying without JSON mode.")
        response = grader_model.invoke(messages)
    reply = response.content
    on_topic = answers_question(reply) if config.GRADER_RELEVANCE_CHECK else True
    if by_sentences:
        return grade_from_sentences(reply, context, answer, question), cited_sentences(reply, sentences), on_topic
    grade = grade_from_quotes(
        reply, context, answer=answer, question=question, strict_quotes=config.GRADER_STRICT_QUOTES
    )
    return grade, verified_quotes(reply, context), on_topic


def grade_answer_with_quotes(grader_model, context: str, question: str, answer: str, agent_name: str = "") -> tuple:
    """(grade, quotes, answers the question): whether the answer is supported by the context, and the evidence
    of the grader that really occurs in it (empty with GRADER_MODE=simple). Fails closed on errors."""
    try:
        if config.GRADER_MODE != "simple":
            return grade_with_evidence(grader_model, context, question, answer, agent_name)
        response = grader_model.invoke(build_grader_messages(context, question, answer))
        return response.content.strip(), [], True
    except Exception as e:
        logger.error(f"[{agent_name}] Grading error, treating answer as unverified: {e}")
        return GRADE_UNAVAILABLE, [], True


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
        refined = response.content.strip() or draft_answer
        allowed = f"{context}\n{question}\n{draft_answer}"
        if config.ANSWER_SCRIPT_CHECK and language in SUPPORTED_LANGUAGES and foreign_script(refined, allowed):
            logger.warning(f"[{agent_name}] The refined answer has text in another script, keeping the draft.")
            return draft_answer
        return refined
    except Exception as e:
        logger.error(f"[{agent_name}] Refinement error, keeping draft: {e}")
        return draft_answer
