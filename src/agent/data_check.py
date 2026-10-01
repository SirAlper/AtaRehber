"""Check that a database answer only states numbers the query returned.

The model explains SQL results in words; a 7B model sometimes miscopies a value ("1.243" for 1234) or adds a
total it computed wrongly. Every number of the explanation must therefore be one of the result's values, the row
count, or a number of the question, allowing for Turkish and English number formats and rounding.
"""

import json
import re
from typing import Any, Dict, Iterable, List, Set

# "1.234,56" or "1,234.56" or "1234.5" or "12"; list markers ("1. ") are removed before
_NUMBER = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s+")
# A rounded value may differ this much (relative), e.g. 1234.567 shown as 1.234,57
_TOLERANCE = 0.005


def _readings(token: str) -> Set[float]:
    """Every value a written number can mean: "1.234" is 1234 in Turkish and 1.234 in English."""
    candidates = set()
    for thousands, decimal in ((".", ","), (",", "."), (" ", ",")):
        text = token.replace(thousands, "").replace(decimal, ".")
        try:
            candidates.add(float(text))
        except ValueError:
            continue
    # The model sometimes uses one sign for both ("120.000.00"): the last one is then the decimal point
    separators = [i for i, char in enumerate(token) if char in ".,"]
    if len(separators) >= 2:
        last = separators[-1]
        candidates.add(float(re.sub(r"[.,\s]", "", token[:last]) + "." + token[last + 1 :]))
    return candidates


def numbers_in(text: str) -> List[Set[float]]:
    """The readings of each number written in a text (list markers left out)."""
    return [_readings(token) for token in _NUMBER.findall(_LIST_MARKER.sub(" ", str(text)))]


def _values(rows: Iterable[Dict[str, Any]]) -> Set[float]:
    values: Set[float] = set()
    for row in rows:
        for value in row.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                values.add(float(value))
            elif value is not None:
                # Dates, codes, and numbers stored as text ("2026-01-15", "SR-2026-103")
                for readings in numbers_in(str(value)):
                    values |= readings
    return values


def _matches(readings: Set[float], allowed: Set[float]) -> bool:
    for reading in readings:
        for value in allowed:
            if reading == value or (value and abs(reading - value) / abs(value) <= _TOLERANCE):
                return True
    return False


def unsupported_data_numbers(answer: str, rows: List[Dict[str, Any]], question: str, row_count: int) -> List[str]:
    """Numbers of the answer that are not values of the result rows, the row count, or numbers of the question."""
    allowed = _values(rows) | {float(row_count)}
    for readings in numbers_in(question):
        allowed |= readings
    tokens = _NUMBER.findall(_LIST_MARKER.sub(" ", str(answer)))
    return [token for token in dict.fromkeys(tokens) if not _matches(_readings(token), allowed)]


def rows_table(columns: List[str], rows: List[Dict[str, Any]], limit: int = 20) -> str:
    """The result rows as a Markdown table (at most `limit` rows)."""
    if not columns:
        return ""

    def cell(value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(row.get(c, "")) for c in columns) + " |" for row in rows[:limit]]
    return "\n".join(lines)
