"""Interpretation of the Self-RAG grader's verdict."""

import json
import re

# Grade recorded when the grader itself fails; treated as "not verified" (fail closed)
GRADE_UNAVAILABLE = "no (grader unavailable)"

# Share of a quote's words that must appear in the context for the quote to count as copied from it; small
# models drop or inflect a word now and then when copying a sentence
QUOTE_MIN_WORD_SHARE = 0.8


def is_grade_passed(grade) -> bool:
    """Interpret a grader verdict: only an answer whose first word is 'yes'/'evet' counts as grounded."""
    words = re.findall(r"\w+", str(grade or "").lower())
    return bool(words) and words[0] in ("yes", "evet")


def _words(text: str) -> list:
    # casefold() maps Turkish "İ" to "i̇"; drop the combining dot so "İzin" and "izin" match
    return re.findall(r"\w+", str(text).replace("İ", "i").replace("I", "ı").casefold())


def quote_in_context(quote: str, context: str) -> bool:
    """True if (nearly) every word of the quote occurs in the context."""
    words = _words(quote)
    if not words:
        return False
    context_words = set(_words(context))
    found = sum(1 for word in words if word in context_words)
    return found / len(words) >= QUOTE_MIN_WORD_SHARE


_JSON_STRING = r'"((?:[^"\\]|\\.)*)"'


def _parse_verdict(raw: str):
    """(supported, problem, quotes) from the grader's JSON, or None if the reply has no verdict.

    A reply cut off by the token limit is not valid JSON; 'supported' comes first, so the verdict and the quotes
    written so far are still read from it.
    """
    text = str(raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "supported" in data:
            quotes = data.get("quotes")
            quotes = quotes if isinstance(quotes, list) else []
            return str(data["supported"]), str(data.get("problem") or ""), [str(q) for q in quotes]
    supported = re.search(r'"supported"\s*:\s*' + _JSON_STRING, text)
    if not supported:
        return None
    problem = re.search(r'"problem"\s*:\s*' + _JSON_STRING, text)
    quotes_start = text.find('"quotes"')
    # A cut-off last quote has no closing quotation mark and is not matched
    quotes = re.findall(_JSON_STRING, text[quotes_start + len('"quotes"') :]) if quotes_start >= 0 else []
    return supported.group(1), problem.group(1) if problem else "", quotes


def verified_quotes(raw: str, context: str) -> list:
    """Quotes of the grader's reply that really occur in the context (the evidence shown with the answer)."""
    verdict = _parse_verdict(raw)
    if verdict is None:
        return []
    return [q.strip() for q in verdict[2] if q.strip() and quote_in_context(q, context)]


def grade_objection(grade: str) -> str:
    """The grader's reason from a failed grade ('no: 65 puan' -> '65 puan'); '' for other grades."""
    grade = str(grade or "").strip()
    if grade == GRADE_UNAVAILABLE or not grade.lower().startswith("no:"):
        return ""
    return grade[3:].strip()


def _numbers(text: str) -> set:
    """Numbers in a text as floats ('2,00' and '2.0' are the same number)."""
    return {float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?(?![.,]?\d)", str(text))}


def numbers_grounded(answer: str, context: str, question: str = "") -> bool:
    """True if every number in the answer also occurs in the context or the question."""
    return _numbers(answer) <= _numbers(context) | _numbers(question)


def phrase_in_context(phrase: str, context: str) -> bool:
    """True if the phrase (two words or more) occurs in the context as a word sequence."""
    words = _words(phrase)
    return len(words) >= 2 and f" {' '.join(words)}" in f" {' '.join(_words(context))} "


def grade_from_quotes(raw: str, context: str, answer: str = "", question: str = "") -> str:
    """Turn the quote grader's JSON into a grade string ('yes' / 'no: <reason>').

    The answer passes if the grader says it is supported and every quote it gives is really in the context: a
    quote the grader made up fails the answer. Empty quotes are ignored.

    A 'no' whose problem is a phrase the context states word for word ("azami yedi yıl") is a grader mistake, as
    the prompt asks for a fact missing from the context; the answer then passes if all its numbers occur in the
    context or the question, so an invented number is still caught.
    """
    verdict = _parse_verdict(raw)
    if verdict is None:
        # Not JSON: fall back to the plain yes/no reading of the reply
        return str(raw or "").strip() or GRADE_UNAVAILABLE
    supported, problem, quotes = verdict
    if not is_grade_passed(supported):
        problem = problem.strip()[:150]
        if answer and phrase_in_context(problem, context) and numbers_grounded(answer, context, question):
            return f"yes (the grader's objection '{problem}' is stated in the documents)"
        return f"no: {problem}" if problem else "no"
    for quote in quotes:
        if quote.strip() and not quote_in_context(quote, context):
            return f"no: quote not found in the documents ({quote.strip()[:150]})"
    return "yes"
