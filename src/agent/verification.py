"""Checking an answer against its sources before it is shown (doc_agent and custom agents).

1. The grader says whether the answer is supported and quotes the context (src/agent/self_rag.py). If it says
   no, a second opinion is asked with its objection to check, as the 7B grader rejects correct answers now and
   then.
2. Code checks what the grader cannot be trusted with:
   * every number of the answer must be in the grader's quotes, the question, or a tool result (the grader may
     quote the right sentence and still accept "30 days" where it says "15 days");
   * an answer that relies only on a transitional article or footnote while a provision in force was also
     retrieved is sent back once (superseded values such as "65 points" instead of the "55 points" in force);
   * an answer to a question that asks for a quantity ("kaç gün", "how many") must state one or say that there
     is none; an answer that only talks about the topic is sent back once (the grader accepts it, since what it
     says is in the documents). GRADER_RELEVANCE_CHECK asks the grader the same for every kind of question.
3. A failed check is refined once with the objection and checked again.
4. Still failed: the sentences of the answer that the quotes cover are shown as a partial answer; if none are,
   the safe fallback. The result is 'verified', 'partial', or 'unverified', with the reasons.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.grading import GRADE_UNAVAILABLE, grade_objection, is_grade_passed
from src.agent.language import message, message_variants
from src.agent.self_rag import grade_answer_with_quotes, grade_with_evidence, refine_answer
from src.core import config
from src.core.logger import get_logger
from src.rag.evidence import attach_evidence
from src.rag.turkish_numbers import spelled_numbers

logger = get_logger("Verification")

VERIFIED, PARTIAL, UNVERIFIED = "verified", "partial", "unverified"
# Reasons shown with the verification level
ISSUE_TRANSITIONAL = "transitional"
ISSUE_PARTIAL = "partial"
# The documents do not answer the question (the answer says so); such questions are listed for staff to answer
NOT_FOUND = "not_found"

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
    r"|\((?:Değişik|Ek|Mülga|İptal)[^)]*\)"
    # Policy sections and codes: "Bölüm 2.1", "Section 4.1", "2.1 maddesi", "SEC-POL-04", "HR-POL-07"
    r"|\b(?:bölüm|bölümü|section|kısım|clause)\s*\d+(?:\.\d+)*"
    r"|\b\d+(?:\.\d+)+\s*(?:no['’]?lu\s*)?(?:madde|bölüm|kısım|section)"
    r"|\b[A-Z]{2,}(?:-[A-Z0-9]{2,})+\b",
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
    # GRADER_RELEVANCE_CHECK: False for a refined answer that still does not give what the question asks for
    answers_question: bool = True


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


# Questions that ask for a quantity ("Kaç gün?", "Ne kadar sürer?", "Yüzde kaç?", "How many days?")
_QUANTITY_QUESTION = re.compile(r"(?i)\bkaç(?:ta|a|ar|er)?\b|\bne kadar\b|\bhow (?:many|much|long|old|often)\b")
# Quantities an answer may state without digits: small numbers in words (the loader adds digits from ten on), and
# "bir" only before a unit, as it is also the indefinite article
_SMALL_NUMBER = re.compile(
    r"(?i)\b(?:yarım|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|birer|ikişer|üçer|çeyrek|buçuk"
    r"|half|one|two|three|four|five|six|seven|eight|nine|ten|once|twice)\b"
    r"|\bbir\s+(?:yıl|ay|gün|hafta|saat|dakika|yarıyıl|dönem|kez|defa|kere|kat|ders|kişi)"
)
# "There is no limit" and "none" also answer a quantity question
_NO_QUANTITY = re.compile(
    r"(?i)\b(?:yok\w*|sınırsız\w*|sınır\w* bulunma\w*|bulunmamakta\w*|hiçbir|no limit|unlimited|none|not limited)\b"
)


def lacks_quantity(question: str, answer: str) -> bool:
    """The question asks for a quantity and the answer states none: no number (references like 'Madde 64' left
    out), no "there is none", and not the "not in the documents" answer."""
    if not _QUANTITY_QUESTION.search(str(question).replace("İ", "i")):
        return False
    if any(text in str(answer) for text in message_variants("no_context")):
        return False
    facts = _REFERENCES.sub(" ", str(answer)).replace("İ", "i")
    return not (numbers(facts) or _SMALL_NUMBER.search(facts) or _NO_QUANTITY.search(facts))


# Clock times: documents write "11.30", answers often "11:30"; both mean the same number
_CLOCK = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def _times_as_numbers(text: str) -> str:
    return _CLOCK.sub(r"\1.\2", str(text))


def numbers(text: str) -> set:
    """Numbers in digits and in Turkish words ('2,00' and '2' are the same number; '11:30' is '11.30')."""
    found = {float(n.replace(",", ".")) for n in _DIGITS.findall(_times_as_numbers(text))}
    return found | spelled_numbers(str(text))


def unsupported_numbers(answer: str, quotes: List[str], question: str, tool_context: str) -> List[str]:
    """Numbers of the answer (references like 'Madde 30' left out) found in none of the quotes, the question, or
    the tool results."""
    allowed = numbers(" ".join(quotes)) | numbers(question) | numbers(tool_context)
    facts = _DIGITS.findall(_times_as_numbers(_REFERENCES.sub(" ", str(answer))))
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
    strict: bool = True,
    agent_name: str = "",
) -> Check:
    """Grader verdict (with a second opinion on 'no') plus the code checks; see the module docstring.

    strict: the first check of an answer; False for a refined answer, whose transitional evidence becomes a
    warning and whose missing quantity is let through (nothing is sent back twice)."""
    full_context = "\n\n".join(part for part in (context, tool_context) if part)
    grade, quotes, on_topic = grade_answer_with_quotes(grader_model, full_context, question, answer, agent_name)
    first_verdict = is_grade_passed(grade)
    if not first_verdict and grade != GRADE_UNAVAILABLE and config.GRADER_SECOND_OPINION:
        second = _second_opinion(grader_model, full_context, question, answer, grade_objection(grade), agent_name)
        if second is not None:
            grade, quotes, on_topic = second
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

    if strict and config.GRADER_QUANTITY_CHECK and lacks_quantity(question, answer):
        objection = (
            "the question asks for a quantity (how many, how much, how long) but the answer states none; state "
            "the number the Context gives for exactly what is asked, or, if the Context does not state it, answer "
            "that the information is not in the documents"
        )
        return Check(False, f"no: {objection}", quotes, objection, first_verdict)

    # The grader's own view of the same thing, for every kind of question; "not in the documents" answers it
    if any(text in str(answer) for text in message_variants("no_context")):
        on_topic = True
    if strict and not on_topic:
        objection = (
            "the answer does not give what the question asks for; answer exactly what is asked from the Context, "
            "or, if the Context does not state it, answer that the information is not in the documents"
        )
        return Check(False, f"no: {objection}", quotes, objection, first_verdict)

    if config.GRADER_TRANSITIONAL_CHECK:
        article = relies_only_on_transitional(attach_evidence(sources, quotes), question)
        if article:
            objection = (
                f"the answer relies on a transitional provision ({article}); use the provision in force from the "
                "Context unless the question asks about the transitional rule"
            )
            if strict:
                return Check(False, f"no: {objection}", quotes, objection, first_verdict)
            return Check(True, grade, quotes, "", first_verdict, [ISSUE_TRANSITIONAL], on_topic)
    return Check(True, grade, quotes, "", first_verdict, answers_question=on_topic)


def _second_opinion(grader_model, context: str, question: str, answer: str, objection: str, agent_name: str):
    """(grade, quotes, answers the question) of a second look at a rejected answer, or None if it fails."""
    try:
        second = grade_with_evidence(grader_model, context, question, answer, agent_name, objection=objection)
    except Exception as e:
        logger.warning(f"[{agent_name}] Second opinion failed: {e}")
        return None
    logger.info(f"[{agent_name}] Second opinion on a rejected answer: {second[0][:80]}")
    return second


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
    result = _verify(
        chat_model, grader_model, context, question, answer, sources, language, tool_context, agent_name, progress
    )
    # What is left after refining still does not state the quantity the question asks for: the documents do not
    # answer the question, and a text about the topic would read as if they did
    if config.GRADER_QUANTITY_CHECK and result.level != UNVERIFIED and lacks_quantity(question, result.answer):
        logger.info(f"[{agent_name}] The answer states no quantity for a question that asks for one: not found.")
        grade = "no: the documents do not state the quantity the question asks for"
        return Verification(message("no_context", language), UNVERIFIED, grade, sources, True, [NOT_FOUND])
    return result


def _verify(
    chat_model, grader_model, context, question, answer, sources, language, tool_context, agent_name, progress
) -> Verification:
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
    if not check.answers_question:
        # Sent back once and still about the topic instead of what was asked: the documents do not answer it
        logger.info(f"[{agent_name}] The refined answer does not give what the question asks for: not found.")
        grade = "no: the documents do not state what the question asks for"
        return Verification(message("no_context", language), UNVERIFIED, grade, sources, True, [NOT_FOUND])
    return Verification(
        answer, VERIFIED, check.grade, attach_evidence(sources, check.quotes), is_refined, list(check.warnings)
    )
