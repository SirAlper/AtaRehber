"""Interpretation of the Self-RAG grader's verdict."""

import re

# Grade recorded when the grader itself fails; treated as "not verified" (fail closed)
GRADE_UNAVAILABLE = "no (grader unavailable)"


def is_grade_passed(grade) -> bool:
    """Interpret a grader verdict: only an answer whose first word is 'yes'/'evet' counts as grounded."""
    words = re.findall(r"\w+", str(grade or "").lower())
    return bool(words) and words[0] in ("yes", "evet")
