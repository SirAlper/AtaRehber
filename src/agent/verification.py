"""Checking an answer against its sources before it is shown (doc_agent and custom agents).

1. The grader says whether the answer is supported and quotes the context (src/agent/self_rag.py). If it says
   no, a second opinion is asked with its objection to check, as the 7B grader rejects correct answers now and
   then.
2. Code checks what the grader cannot be trusted with:
   * every number of the answer must be in the grader's quotes, the question, or a tool result (the grader may
     quote the right sentence and still accept "30 days" where it says "15 days");
   * an answer that relies only on a transitional article or footnote while a provision in force was also
     retrieved is sent back once (superseded values such as "65 points" instead of the "55 points" in force).
3. A failed check is refined once with the objection and checked again.
4. Still failed: the sentences of the answer that the quotes cover are shown as a partial answer; if none are,
   the safe fallback. The result is 'verified', 'partial', or 'unverified', with the reasons.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.grading import GRADE_UNAVAILABLE, grade_objection, is_grade_passed, verified_quotes
from src.agent.language import message
from src.agent.llm import json_mode
from src.agent.prompts import build_second_opinion_messages
from src.agent.self_rag import grade_answer_with_quotes, refine_answer
from src.core import config
from src.core.logger import get_logger
from src.rag.evidence import attach_evidence
from src.rag.turkish_numbers import spelled_numbers

logger = get_logger("Verification")

VERIFIED, PARTIAL, UNVERIFIED = "verified", "partial", "unverified"
# Reasons shown with the verification level
ISSUE_TRANSITIONAL = "transitional"
ISSUE_PARTIAL = "partial"

# Numbers in an answer that are references, not facts: "Madde 30", "30/2", "54 üncü maddesi", "2547 sayılı"
_REFERENCES = re.compile(
    # "Madde 30", "Madde 30/2", "Madde 17(2)", "Madde 32, 1"
    r"(?i)\b(?:madde|md\.?|article)\s*\d+(?:\s*/\s*[\dA-Za-zÇĞİÖŞÜçğıöşü]+|\s*\(\d+\)|\s*,\s*\d+\b)*"
    # "54 üncü madde", "30. madde", "(2) numaralı fıkra"
    r"|\b\d+\s*['’]?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|\.)\s*(?:madde|fıkra|bent|md)"
    r"|\b\d+\s*sayılı"
    # Paragraph and item markers: "(1) ve (3)", "a) 1) ve 2) numaralı", list numbers
    r"|\(\d{1,2}\)|\b\d{1,2}\)|^\s*\d+[.)]\s"
    # Amendment notes: "(Değişik:RG-14/4/2024-32517)", "(Ek: 18/6/2017-7033/14 md.)"
    r"|\((?:Değişik|Ek|Mülga|İptal)[^)]*\)",
    re.MULTILINE,
)
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?(?![.,]?\d)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
# Share of a sentence's words the quotes must contain for the sentence to be kept in a partial answer
PARTIAL_MIN_SHARE = 0.5


@dataclass
class Check:
    """One check of an answer: passed or the objection, the grader's grade and verified quotes."""

    passed: bool
    grade: str
    quotes: List[str]
    objection: str = ""
    first_verdict: bool = False  # the grader's first verdict, before the second opinion and the code checks
    warnings: List[str] = field(default_factory=list)


@dataclass
class Verification:
    answer: str
    level: str
    grade: str
    sources: List[Dict[str, Any]]
    is_refined: bool = False
    issues: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "issues": list(self.issues)}


def numbers(text: str) -> set:
    """Numbers in digits and in Turkish words ('2,00' and '2' are the same number)."""
    found = {float(n.replace(",", ".")) for n in _DIGITS.findall(str(text))}
    return found | spelled_numbers(str(text))


def unsupported_numbers(answer: str, quotes: List[str], question: str, tool_context: str) -> List[str]:
    """Numbers of the answer (references like 'Madde 30' left out) found in none of the quotes, the question, or
    the tool results."""
    allowed = numbers(" ".join(quotes)) | numbers(question) | numbers(tool_context)
    facts = _DIGITS.findall(_REFERENCES.sub(" ", str(answer)))
    return [n for n in dict.fromkeys(facts) if float(n.replace(",", ".")) not in allowed]


def _is_transitional(source: Dict[str, Any]) -> bool:
    return str(source.get("article") or "").startswith(("Geçici Madde", "Dipnotlar"))


def relies_only_on_transitional(sources: List[Dict[str, Any]], question: str) -> Optional[str]:
    """The transitional article the evidence comes from, if all of it does while a provision in force was also
    retrieved; None otherwise (or when the question asks about transitional provisions)."""
    if re.search(r"(?i)geçici|transitional", question):
        return None
    used = [s for s in sources if s.get("used")]
    if not used or not all(_is_transitional(s) for s in used):
        return None
    if not any(s.get("article") and not _is_transitional(s) for s in sources):
        return None
    return str(used[0].get("article"))


def _stems(text: str) -> List[str]:
    # Turkish words carry suffixes ("süresi", "gündür"); the first five letters of longer words compare stems
    return [w[:5] for w in re.findall(r"\w+", str(text).replace("İ", "i").casefold()) if len(w) > 3]


def partial_answer(answer: str, quotes: List[str], question: str, tool_context: str) -> str:
    """The sentences of the answer the quotes support; '' if none or all of them are.

    A sentence with numbers is kept if all its numbers (digits or words) are in the quotes, the question, or the
    tool results; a sentence without numbers if most of its word stems are in the quotes.
    """
    allowed = numbers(" ".join(quotes)) | numbers(question) | numbers(tool_context)
    quote_stems = set(_stems(" ".join(quotes)))
    sentences = [s.strip() for s in _SENTENCE_END.split(str(answer)) if s.strip()]
    kept = []
    for sentence in sentences:
        values = numbers(_REFERENCES.sub(" ", sentence))
        if values:
            supported = values <= allowed
        else:
            stems = _stems(sentence)
            supported = bool(stems) and sum(s in quote_stems for s in stems) / len(stems) >= PARTIAL_MIN_SHARE
        if supported:
            kept.append(sentence)
    return " ".join(kept) if 0 < len(kept) < len(sentences) else ""


def check_answer(
    grader_model,
    context: str,
    question: str,
    answer: str,
    sources: List[Dict[str, Any]],
    tool_context: str = "",
    strict_transitional: bool = True,
    agent_name: str = "",
) -> Check:
    """Grader verdict (with a second opinion on 'no') plus the code checks; see the module docstring."""
    full_context = "\n\n".join(part for part in (context, tool_context) if part)
    grade, quotes = grade_answer_with_quotes(grader_model, full_context, question, answer, agent_name)
    first_verdict = is_grade_passed(grade)
    if not first_verdict and grade != GRADE_UNAVAILABLE and config.GRADER_SECOND_OPINION:
        second = _second_opinion(grader_model, full_context, question, answer, grade_objection(grade), agent_name)
        if second is not None:
            grade, quotes = second
    if not is_grade_passed(grade):
        return Check(False, grade, quotes, grade_objection(grade), first_verdict)

    # The grader may quote nothing (a short answer); the number check needs quotes to compare with. Numbers count
    # when they are in the quotes or in the chunks the quotes come from (the grader copies the rule, not always
    # the numbers next to it, e.g. "3,00-3,49"); a number from another article still fails.
    if quotes and config.GRADER_NUMBER_CHECK:
        quoted_chunks = [s.get("content", "") for s in attach_evidence(sources, quotes) if s.get("used")]
        missing = unsupported_numbers(answer, quotes + quoted_chunks, question, tool_context)
        if missing:
            objection = f"the number(s) {', '.join(missing)} are not stated in the quoted articles"
            return Check(False, f"no: {objection}", quotes, objection, first_verdict)

    if config.GRADER_TRANSITIONAL_CHECK:
        article = relies_only_on_transitional(attach_evidence(sources, quotes), question)
        if article:
            objection = (
                f"the answer relies on a transitional provision ({article}); use the provision in force from the "
                "Context unless the question asks about the transitional rule"
            )
            if strict_transitional:
                return Check(False, f"no: {objection}", quotes, objection, first_verdict)
            return Check(True, grade, quotes, "", first_verdict, warnings=[ISSUE_TRANSITIONAL])
    return Check(True, grade, quotes, "", first_verdict)


def _second_opinion(grader_model, context: str, question: str, answer: str, objection: str, agent_name: str):
    """(grade, quotes) of a second look at a rejected answer, or None if it fails."""
    from src.agent.grading import grade_from_quotes

    messages = build_second_opinion_messages(context, question, answer, objection)
    try:
        try:
            response = json_mode(grader_model).invoke(messages)
        except Exception:
            response = grader_model.invoke(messages)
    except Exception as e:
        logger.warning(f"[{agent_name}] Second opinion failed: {e}")
        return None
    grade = grade_from_quotes(response.content, context, answer=answer, question=question)
    logger.info(f"[{agent_name}] Second opinion on a rejected answer: {grade[:80]}")
    return grade, verified_quotes(response.content, context)


def verify_answer(
    chat_model,
    grader_model,
    context: str,
    question: str,
    answer: str,
    sources: List[Dict[str, Any]],
    language: str,
    tool_context: str = "",
    agent_name: str = "",
    progress: Optional[Callable[[str], None]] = None,
) -> Verification:
    """Check, refine once, and fall back to a partial answer or the safe answer; see the module docstring."""
    report = progress or (lambda stage: None)
    report("verifying")
    check = check_answer(grader_model, context, question, answer, sources, tool_context, True, agent_name)
    is_refined = False
    if not check.passed:
        logger.info(f"[{agent_name}] Answer not grounded ('{check.grade}'), refining...")
        report("refining")
        check_context = "\n\n".join(part for part in (context, tool_context) if part)
        refined = refine_answer(chat_model, check_context, question, answer, language, check.objection, agent_name)
        is_refined = True
        recheck = check_answer(grader_model, context, question, refined, sources, tool_context, False, agent_name)
        if recheck.passed:
            answer, check = refined, recheck
        else:
            # Keep what the quotes of either round cover, from the answer the user would have seen
            quotes = recheck.quotes or check.quotes
            partial = partial_answer(refined, quotes, question, tool_context) or partial_answer(
                answer, quotes, question, tool_context
            )
            if partial:
                logger.info(f"[{agent_name}] Showing the verified part of the answer only.")
                return Verification(
                    partial,
                    PARTIAL,
                    f"partial: {recheck.objection or check.objection}",
                    attach_evidence(sources, quotes),
                    True,
                    [ISSUE_PARTIAL],
                )
            logger.warning(f"[{agent_name}] Refined answer still unverified, using safe fallback.")
            return Verification(message("fallback", language), UNVERIFIED, recheck.grade, sources, True)
    return Verification(
        answer, VERIFIED, check.grade, attach_evidence(sources, check.quotes), is_refined, list(check.warnings)
    )
