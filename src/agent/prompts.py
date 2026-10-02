import re
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
    "6. If a provision refers to another provision that is also in the Context (e.g. 'Kanunun 54 üncü maddesine "
    "göre'), also state what that provision says for the question, e.g. the specific penalty.\n"
    "7. When the Context shows an article or section number for the rule you use, cite it (e.g. 'Madde 30').\n"
    "8. Ensure sentences and bullet points are fully and cleanly finished."
)

# ANSWER_EVIDENCE_FIRST: copying the supporting sentence before answering keeps a small model from mixing up two
# rules of one sentence or two neighbouring list items
EVIDENCE_FIRST_RULE = (
    "Reply in exactly this format:\n"
    'EVIDENCE: "<the sentence(s) of the Context your answer relies on, copied word for word>"\n'
    "ANSWER: <your answer>\n"
    "Write EVIDENCE: none if the Context does not answer the question. Keep the words EVIDENCE and ANSWER."
)

SYSTEM_PROMPT_GRADER = (
    "You are a factual auditor. Review the provided Context and the generated Answer.\n"
    "Are the core facts and claims in the Answer fully supported by the Context?\n"
    "Paraphrasing, stylistic wording, or summarization is NOT considered hallucination.\n"
    "If the answer is supported, write only 'yes'. If there is fabricated or contradictory information, write only 'no'. "
    "Do not write anything else."
)

_GRADER_RULES = (
    "You are a factual auditor. Check whether the Answer is supported by the Context.\n"
    "- 'supported' is 'yes' if the key facts of the Answer (numbers, durations, deadlines, penalties, conditions, "
    "bodies, names) are stated in the Context. Paraphrasing and summarizing are fine.\n"
    "- It is 'no' if a key fact is missing from the Context or the Context states something different (another "
    "number, another penalty, a different condition); 'problem' then names that fact in a few words.\n"
)
# How the grader shows its evidence (GRADER_MODE): copied words, or the numbers of the Context's sentences. A
# model that garbles Turkish letters while copying loses correct answers with "quotes"; numbers cannot be garbled.
_GRADER_EVIDENCE = {
    "quotes": (
        "- 'quotes': for each key fact, copy the words of the Context that state it, word for word "
        "(at most 25 words each, at most 4 quotes).\n",
        '"quotes": ["..."]',
    ),
    "sentences": (
        "- 'sentences': the sentences of the Context are numbered in square brackets ([1], [2], ...); for each key "
        "fact, give the number of the sentence that states it (at most 6 numbers).\n",
        '"sentences": []',
    ),
}
# GRADER_RELEVANCE_CHECK: an answer can be supported and still not answer the question (it talks about the topic)
_GRADER_RELEVANCE_RULE = (
    "- 'answers_question' is 'no' if the Answer does not give what the Question asks for: the Question asks for "
    "a number, a duration, a date, a name, or a yes or no and the Answer gives none, or the Answer is about "
    "something else. It is 'yes' otherwise, also for an Answer saying that the documents do not state it.\n"
)


def grader_system_prompt(mode: str = "quotes", relevance: bool = False) -> str:
    """System prompt of the grader that shows its evidence; mode: "quotes" or "sentences"."""
    rule, example = _GRADER_EVIDENCE[mode]
    fields = '"supported": "yes", "problem": "", ' + ('"answers_question": "yes", ' if relevance else "") + example
    return f"{_GRADER_RULES}{_GRADER_RELEVANCE_RULE if relevance else ''}{rule}Reply with JSON only: {{{fields}}}"


SYSTEM_PROMPT_GRADER_QUOTES = grader_system_prompt()

SYSTEM_PROMPT_REFINE = (
    "You are an editor and verification specialist.\n"
    "Review the Context, Question, and the previously generated Draft Answer.\n"
    "Some statements in the draft answer may not be fully grounded in the documents.\n"
    "Your task:\n"
    "1. Completely remove (prune) any unsupported claims, assumptions, or speculations not directly verified by the Context.\n"
    "2. If an Auditor's objection is given, correct or remove that claim using the Context, and keep the other facts "
    "of the draft that the Context states.\n"
    "3. Reconstruct a concise, professional response, retaining ONLY verified facts.\n"
    f"4. Only if the Context contains nothing that answers the question, write only: '{NO_CONTEXT_RESPONSE}'\n"
    "5. Ensure sentences are complete and grammatically fluent."
)

SYSTEM_PROMPT_CLARIFY = (
    "Look at the rules in the Context that answer the user's Question about their own situation.\n"
    '- "depends_on": if the answer to THIS Question differs between cases (different numbers, limits, durations, '
    "or permissions), name the condition that decides the case in a few words (for example seniority, domestic or "
    'abroad, the kind of leave, degree level); "" if this Question has one answer for everyone (a rule that '
    "applies to all), even if other rules in the Context have cases.\n"
    '- "stated": true if the Question or the information about the user already says which case applies.\n'
    '- "question": one short question asking the user which case applies; "options": 2 to 4 short answers, one '
    "per case.\n"
    'Reply with JSON only: {"depends_on": "", "stated": false, "question": "", "options": []}'
)

SYSTEM_PROMPT_SYNTHESIS = (
    "You combine the partial answers of several specialist agents into one final answer to the user's question.\n"
    "Rules:\n"
    "1. Use ONLY the facts in the partial answers; do not add information. You may draw the conclusion the "
    "question asks for from them: compare two values, compute a difference or a sum, say whether a condition is met.\n"
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


def step_context_text(step_context: Optional[list]) -> str:
    """Answers of earlier plan steps a step builds on, as a prompt section ("" when there are none).

    step_context: dicts with 'agent', 'question', 'answer' (see MultiAgentOrchestrator, plan steps with "uses").
    """
    if not step_context:
        return ""
    parts = [f"[{item['agent']}] {item['question']}\n{item['answer']}" for item in step_context]
    return "Answers of earlier steps (facts you may use):\n" + "\n\n".join(parts) + "\n\n"


def _with_language(system_prompt: str, language: Optional[str]) -> str:
    return f"{system_prompt}\n{language_instruction(language)}" if language else system_prompt


def build_rag_messages(
    context: str,
    question: str,
    chat_history: list = None,
    language: Optional[str] = None,
    evidence_first: bool = False,
    user_note: str = "",
    earlier_steps: str = "",
) -> list:
    """Build LangChain message list for enterprise RAG response generation.

    language: response language code ('tr', 'en'); None leaves the language to the model.
    evidence_first: the model copies its evidence before answering (EVIDENCE / ANSWER lines, see split_evidence).
    user_note: the asking user's unit, program, and level (src/auth/profile.py), if known.
    earlier_steps: answers of earlier plan steps this step builds on (see step_context_text).
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

    system_prompt = f"{SYSTEM_PROMPT_RAG}\n{EVIDENCE_FIRST_RULE}" if evidence_first else SYSTEM_PROMPT_RAG
    if user_note:
        system_prompt = f"{system_prompt}\n{user_note}"
    return [
        SystemMessage(content=_with_language(system_prompt, language)),
        HumanMessage(content=f"{history_str}{earlier_steps}Context:\n{context}\n\nQuestion: {question}"),
    ]


# Markers of an evidence-first reply; the model sometimes translates them into the answer language
_ANSWER_MARKER = re.compile(r"^\s*\**(ANSWER|CEVAP|YANIT)\**\s*:\s*", re.IGNORECASE | re.MULTILINE)
_EVIDENCE_MARKER = re.compile(r"^\s*\**(EVIDENCE|DAYANAK|KANIT)\**\s*:", re.IGNORECASE | re.MULTILINE)
_QUOTED = re.compile(r'"([^"\n]{8,})"|“([^”\n]{8,})”')


def split_evidence(reply: str) -> tuple:
    """(quotes, answer) of an evidence-first reply; a reply without the markers is all answer."""
    text = str(reply or "").strip()
    answer_marker = _ANSWER_MARKER.search(text)
    if not answer_marker:
        if _EVIDENCE_MARKER.match(text):
            # Only evidence: drop the evidence line so it is not shown as the answer
            text = text.split("\n", 1)[1].strip() if "\n" in text else ""
        return [], text
    evidence = text[: answer_marker.start()]
    quotes = [a or b for a, b in _QUOTED.findall(evidence)]
    return quotes, text[answer_marker.end() :].strip()


SYSTEM_PROMPT_SYNTHESIS_GRADER = (
    f"{SYSTEM_PROMPT_GRADER}\n"
    "The Context is the partial answers of several agents. A conclusion drawn from them (a comparison, a difference "
    "or sum of their numbers, whether a condition they state is met) counts as supported."
)


def build_synthesis_grader_messages(partial_answers: str, question: str, answer: str) -> list:
    """Grader messages for a combined answer: conclusions drawn from the partial answers are allowed."""
    return [
        SystemMessage(content=SYSTEM_PROMPT_SYNTHESIS_GRADER),
        HumanMessage(content=f"Context:\n{partial_answers}\n\nQuestion: {question}\n\nAnswer:\n{answer}"),
    ]


def build_grader_messages(context: str, question: str, answer: str) -> list:
    """Build LangChain message list for hallucination auditing."""
    return [
        SystemMessage(content=SYSTEM_PROMPT_GRADER),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:\n{answer}"),
    ]


SECOND_OPINION_NOTE = (
    'Another auditor rejected this Answer with the objection: "{objection}". Check that objection against the '
    "Context yourself: it may be wrong. Reject the Answer only if the Context really does not state a key fact of it "
    "or states something different."
)


def build_evidence_grader_messages(
    context: str,
    question: str,
    answer: str,
    mode: str = "quotes",
    relevance: bool = False,
    objection: Optional[str] = None,
) -> list:
    """Messages for the grader that backs every fact of the answer with evidence from the context.

    mode: "quotes" (copied words) or "sentences" (numbers; the context must then be numbered, see
    number_sentences in src/agent/grading.py). relevance: also ask whether the answer gives what is asked.
    objection: a second look at an answer the grader rejected, with the first objection to check ("" if it gave
    none); None for the first look.
    """
    system_prompt = grader_system_prompt(mode, relevance)
    if objection is not None:
        system_prompt += "\n" + SECOND_OPINION_NOTE.format(objection=objection or "no reason given")
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:\n{answer}"),
    ]


def build_refine_messages(
    context: str, question: str, draft_answer: str, language: Optional[str] = None, objection: str = ""
) -> list:
    """Build LangChain message list to prune and refine ungrounded answers.

    objection: what the grader found unsupported, if it said so; the editor then fixes that claim instead of
    rewriting the whole answer.
    """
    system_prompt = SYSTEM_PROMPT_REFINE
    if language:
        # The "nothing verifiable" sentence the refiner may return must be in the response language too
        system_prompt = system_prompt.replace(NO_CONTEXT_RESPONSE, message("no_context", language))
    return [
        SystemMessage(content=_with_language(system_prompt, language)),
        HumanMessage(
            content=f"Context:\n{context}\n\nQuestion: {question}\n\nDraft Answer:\n{draft_answer}"
            + (f"\n\nAuditor's objection: {objection}" if objection else "")
        ),
    ]


def build_clarify_messages(context: str, question: str, language: Optional[str] = None, user_note: str = "") -> list:
    """Messages asking whether the answer depends on something about the asker that the question does not say."""
    note = f"{user_note}\n\n" if user_note else ""
    return [
        SystemMessage(content=_with_language(SYSTEM_PROMPT_CLARIFY, language)),
        HumanMessage(content=f"{note}Context:\n{context}\n\nQuestion: {question}"),
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


def build_rewrite_messages(question: str, chat_history: list, user_note: str = "") -> list:
    """Build LangChain message list for dynamic query rewriting and expansion.

    user_note: the asking user's unit, program, and level, so "my department" becomes the department's name.
    """
    history_lines = [
        f"User: {turn.get('question', '')}\nAssistant: {turn.get('answer', '')}"
        for turn in chat_history[-3:]
        if turn.get("question") and turn.get("answer")
    ]
    history_str = "\n".join(history_lines) if history_lines else "No prior conversation."

    system_prompt = f"{SYSTEM_PROMPT_REWRITE}\n{user_note}" if user_note else SYSTEM_PROMPT_REWRITE
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Conversation History:\n{history_str}\n\nCurrent Question: {question}"),
    ]
