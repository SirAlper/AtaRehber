from langchain_core.messages import SystemMessage, HumanMessage


# ──────────────────────────── SYSTEM PROMPTS ────────────────────────────

SYSTEM_PROMPT_RAG = (
    "You are an enterprise AI assistant.\n"
    "Answer the user's question clearly, completely, and professionally, "
    "adhering strictly to the provided company documents in the Context.\n"
    "Rules:\n"
    "1. Answer ONLY with information directly relevant to the question.\n"
    "2. If the Context contains unrelated topics (e.g., hardware, leave policy, budget), do not include them in the answer.\n"
    "3. Never fabricate or hallucinate any information not present in the documents.\n"
    "4. Ensure sentences and bullet points are fully and cleanly finished."
)

SYSTEM_PROMPT_GRADER = (
    "You are a factual auditor. Review the provided Context and the generated Answer.\n"
    "Are the core facts and claims in the Answer fully supported by the Context?\n"
    "Paraphrasing, stylistic wording, or summarization is NOT considered hallucination.\n"
    "If the answer is supported, write only 'yes'. If there is fabricated or contradictory information, write only 'no'. "
    "Do not write anything else."
)

SYSTEM_PROMPT_REFINE = (
    "You are an enterprise editor and verification specialist.\n"
    "Review the Context, Question, and the previously generated Draft Answer.\n"
    "Some statements in the draft answer may not be fully grounded in company documents.\n"
    "Your task:\n"
    "1. Completely remove (prune) any unsupported claims, assumptions, or speculations not directly verified by the Context.\n"
    "2. Reconstruct a concise, professional response, retaining ONLY verified facts.\n"
    "3. If no verifiable information remains to answer the question, write only: 'This information is not found in company documents.'\n"
    "4. Ensure sentences are complete and grammatically fluent."
)

NO_CONTEXT_RESPONSE = "This information is not found in company documents."

FALLBACK_RESPONSE = "This information cannot be fully verified against company documents."

SYSTEM_PROMPT_REWRITE = (
    "You are a search query optimizer. Given the user's current question and recent conversation history, "
    "rewrite the question into a clear, specific, standalone search query optimized for document retrieval.\n"
    "Rules:\n"
    "1. Resolve pronouns and references using conversation history (e.g., 'it' → the actual subject).\n"
    "2. Keep the rewritten query concise (under 50 words).\n"
    "3. Return ONLY the rewritten query text, nothing else."
)


# ──────────────────────────── MESSAGE BUILDERS ────────────────────────────


def build_rag_messages(context: str, question: str, chat_history: list = None) -> list:
    """Build LangChain message list for enterprise RAG response generation."""
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
        SystemMessage(content=SYSTEM_PROMPT_RAG),
        HumanMessage(content=f"{history_str}Context:\n{context}\n\nQuestion: {question}"),
    ]


def build_grader_messages(context: str, question: str, answer: str) -> list:
    """Build LangChain message list for hallucination auditing."""
    return [
        SystemMessage(content=SYSTEM_PROMPT_GRADER),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:\n{answer}"),
    ]


def build_refine_messages(context: str, question: str, draft_answer: str) -> list:
    """Build LangChain message list to prune and refine ungrounded answers."""
    return [
        SystemMessage(content=SYSTEM_PROMPT_REFINE),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}\n\nDraft Answer:\n{draft_answer}"),
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
