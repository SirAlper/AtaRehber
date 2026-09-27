from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.language import language_instruction, message
from src.core.config import ORGANIZATION_NAME

# "Example University" or a neutral wording; the assistant serves companies, universities, and public bodies
ORGANIZATION = ORGANIZATION_NAME or "the organization"

# English wording; agents use message("no_context" / "fallback", language) for the user's language
NO_CONTEXT_RESPONSE = message("no_context", "en")

FALLBACK_RESPONSE = message("fallback", "en")


# ──────────────────────────── SYSTEM PROMPTS ────────────────────────────

SYSTEM_PROMPT_RAG = (
    f"You are the AI assistant of {ORGANIZATION}.\n"
    "Answer the user's question clearly, completely, and professionally, adhering strictly to the documents "
    "(regulations, policies, procedures, guidelines) provided in the Context.\n"
    "Rules:\n"
    "1. Answer ONLY with information directly relevant to the question.\n"
    "2. If the Context contains unrelated topics, do not include them in the answer.\n"
    "3. Never fabricate or hallucinate any information not present in the documents.\n"
    "4. Give the general rule first. Present an exception (introduced by words such as 'however', 'except', "
    "'ancak', 'hariç') only as an exception and say when it applies; never answer with the exception as if it "
    "were the general rule.\n"
    "5. Prefer provisions currently in force. Transitional or temporary articles (e.g. 'Geçici Madde'), footnotes, "
    "and amendment notes may contain old or superseded values; use them only when the question is about them.\n"
    "6. When the Context shows an article or section number for the rule you use, cite it (e.g. 'Madde 30').\n"
    "7. Ensure sentences and bullet points are fully and cleanly finished."
)

SYSTEM_PROMPT_GRADER = (
    "You are a factual auditor. Review the provided Context and the generated Answer.\n"
    "Are the core facts and claims in the Answer fully supported by the Context?\n"
    "Paraphrasing, stylistic wording, or summarization is NOT considered hallucination.\n"
    "If the answer is supported, write only 'yes'. If there is fabricated or contradictory information, write only 'no'. "
    "Do not write anything else."
)

SYSTEM_PROMPT_REFINE = (
    "You are an editor and verification specialist.\n"
    "Review the Context, Question, and the previously generated Draft Answer.\n"
    "Some statements in the draft answer may not be fully grounded in the documents.\n"
    "Your task:\n"
    "1. Completely remove (prune) any unsupported claims, assumptions, or speculations not directly verified by the Context.\n"
    "2. Reconstruct a concise, professional response, retaining ONLY verified facts.\n"
    f"3. If no verifiable information remains to answer the question, write only: '{NO_CONTEXT_RESPONSE}'\n"
    "4. Ensure sentences are complete and grammatically fluent."
)

SYSTEM_PROMPT_SYNTHESIS = (
    "You combine the partial answers of several specialist agents into one final answer to the user's question.\n"
    "Rules:\n"
    "1. Use ONLY the facts in the partial answers; do not add information.\n"
    "2. Keep every number, date, verdict label, and article reference exactly as written.\n"
    "3. If a partial answer says the information was not found or could not be verified, say so for that part.\n"
    "4. Answer the whole question in one coherent response; use short sections or bullet points when it helps."
)

SYSTEM_PROMPT_REWRITE = (
    "You are a search query optimizer. Given the user's current question and recent conversation history, "
    "rewrite the question into a clear, specific, standalone search query optimized for document retrieval.\n"
    "Rules:\n"
    "1. Resolve pronouns and references using conversation history (e.g., 'it' → the actual subject).\n"
    "2. Keep the rewritten query concise (under 50 words).\n"
    "3. Return ONLY the rewritten query text, nothing else."
)


# ──────────────────────────── MESSAGE BUILDERS ────────────────────────────


def _with_language(system_prompt: str, language: Optional[str]) -> str:
    return f"{system_prompt}\n{language_instruction(language)}" if language else system_prompt


def build_rag_messages(context: str, question: str, chat_history: list = None, language: Optional[str] = None) -> list:
    """Build LangChain message list for enterprise RAG response generation.

    language: response language code ('tr', 'en'); None leaves the language to the model.
    """
    history_str = ""
    if chat_history:
        history_lines = [
            f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')}"
            for turn in chat_history[-3:]
            if turn.get("question") and turn.get("answer")
        ]
        if history_lines:
            history_str = "Recent Conversation History:\n" + "\n".join(history_lines) + "\n\n"

    return [
        SystemMessage(content=_with_language(SYSTEM_PROMPT_RAG, language)),
        HumanMessage(content=f"{history_str}Context:\n{context}\n\nQuestion: {question}"),
    ]


def build_grader_messages(context: str, question: str, answer: str) -> list:
    """Build LangChain message list for hallucination auditing."""
    return [
        SystemMessage(content=SYSTEM_PROMPT_GRADER),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:\n{answer}"),
    ]


def build_refine_messages(context: str, question: str, draft_answer: str, language: Optional[str] = None) -> list:
    """Build LangChain message list to prune and refine ungrounded answers."""
    system_prompt = SYSTEM_PROMPT_REFINE
    if language:
        # The "nothing verifiable" sentence the refiner may return must be in the response language too
        system_prompt = system_prompt.replace(NO_CONTEXT_RESPONSE, message("no_context", language))
    return [
        SystemMessage(content=_with_language(system_prompt, language)),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nDraft Answer:\n{draft_answer}"),
    ]


def build_synthesis_messages(question: str, parts: list, language: Optional[str] = None) -> list:
    """Build messages that merge partial answers into one; parts: dicts with 'agent', 'question', 'answer'."""
    sections = "\n\n".join(
        f"[Part {index}: {part['agent']}]\nSub-question: {part['question']}\nPartial answer:\n{part['answer']}"
        for index, part in enumerate(parts, 1)
    )
    return [
        SystemMessage(content=_with_language(SYSTEM_PROMPT_SYNTHESIS, language)),
        HumanMessage(content=f"User question: {question}\n\n{sections}"),
    ]


def build_rewrite_messages(question: str, chat_history: list) -> list:
    """Build LangChain message list for dynamic query rewriting and expansion."""
    history_lines = [
        f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')}"
        for turn in chat_history[-3:]
        if turn.get("question") and turn.get("answer")
    ]
    history_str = "\n".join(history_lines) if history_lines else "No prior conversation."

    return [
        SystemMessage(content=SYSTEM_PROMPT_REWRITE),
        HumanMessage(content=f"Conversation History:\n{history_str}\n\nCurrent Question: {question}"),
    ]
