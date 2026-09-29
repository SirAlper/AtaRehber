"""Evidence shown with an answer: the sentences of the sources that the grader quoted, with a citation.

The grader copies the words of the context that support the answer (see src/agent/grading.py). A copy can drop
or inflect a word, so each quote is matched to the sentence of a source that contains most of its words, and
that original sentence is shown, with the article and paragraph it belongs to ("Madde 30/2").
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# Chunk header added by the document loader: "[YÜKSEKÖĞRETİM KANUNU | Madde 30 – Emeklilik yaş haddi]"
_HEADER = re.compile(r"^\[[^\]\n]*\]\n")
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|\n+")
# Paragraph markers of legislation at the start of a line: "(2) Birinci fıkrada ..."
_PARAGRAPH = re.compile(r"^\s*\((\d+)\)", re.MULTILINE)
# Share of a quote's words a sentence must contain to count as its source
MIN_MATCH = 0.6
# Consecutive sentences a single quote may span
MAX_SENTENCES = 3


def display_text(content: str) -> str:
    """Chunk text without the loader's header line (the source title shows document and article already)."""
    return _HEADER.sub("", str(content or ""), count=1).strip()


def _words(text: str) -> List[str]:
    return re.findall(r"\w+", str(text).replace("İ", "i").replace("I", "ı").casefold())


def _sentences(text: str) -> List[Tuple[int, int]]:
    spans, position = [], 0
    for match in _SENTENCE_END.finditer(text):
        if text[position : match.start()].strip():
            spans.append((position, match.start()))
        position = match.end()
    if text[position:].strip():
        spans.append((position, len(text)))
    return spans


def locate(quote: str, text: str) -> Optional[Tuple[float, int, str]]:
    """(match share, start offset, original sentences) of the passage of `text` the quote was copied from."""
    quote_words = set(_words(quote))
    if not quote_words:
        return None
    spans = _sentences(text)
    best = None
    for first in range(len(spans)):
        for last in range(first, min(first + MAX_SENTENCES, len(spans))):
            start, end = spans[first][0], spans[last][1]
            share = len(quote_words & set(_words(text[start:end]))) / len(quote_words)
            passage = text[start:end].strip()
            # Prefer the best match; among equal matches the shortest passage (its citation is the most precise)
            if best is None or share > best[0] + 1e-9 or (abs(share - best[0]) <= 1e-9 and len(passage) < len(best[2])):
                best = (share, start, passage)
            if share >= 1.0:
                break
    if best is None or best[0] < MIN_MATCH:
        return None
    return best


def citation(source: Dict[str, Any], text: str, offset: int) -> str:
    """'Madde 30/2' for a passage of a legislation chunk: the article and the last paragraph marker before it."""
    article = str(source.get("article") or "").split(" – ")[0].strip()
    if not article.startswith(("Madde", "Geçici Madde", "Ek Madde")):
        return article
    paragraphs = [m.group(1) for m in _PARAGRAPH.finditer(text) if m.start() <= offset]
    return f"{article}/{paragraphs[-1]}" if paragraphs else article


def attach_evidence(sources: List[Dict[str, Any]], quotes: List[str]) -> List[Dict[str, Any]]:
    """Sources with the quoted sentences as `evidence` ([{"text", "citation"}]) and `used`; used sources first."""
    result = [dict(source) for source in sources]
    for quote in quotes:
        best = None
        for index, source in enumerate(result):
            text = display_text(source.get("content", ""))
            found = locate(quote, text)
            if found and (best is None or found[0] > best[0]):
                best = (found[0], index, found[1], found[2], text)
        if best is None:
            continue
        _, index, offset, sentence, text = best
        source = result[index]
        evidence = source.setdefault("evidence", [])
        if all(item["text"] != sentence for item in evidence):
            evidence.append({"text": sentence, "citation": citation(source, text, offset)})
        source["used"] = True
    return sorted(result, key=lambda source: not source.get("used"))
