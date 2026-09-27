"""Model-free scoring helpers for the evaluation harness.

Everything here is deterministic so it can be unit tested without loading any model.
"""

import json
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

Fact = Union[str, List[str]]

CATEGORIES = ("document", "compliance", "database", "greeting", "out_of_scope")
# Categories answered from the vector store; their retrieval quality is measured directly
RETRIEVAL_CATEGORIES = ("document", "compliance", "out_of_scope")

# Phrases that mark an answer as "I don't know" (system fallbacks in English, model answers in Turkish/English)
REFUSAL_MARKERS = (
    "not found in company documents",
    "cannot be fully verified",
    "doğrulanamadı",
    "no written policy",
    "no relevant policy",
    "[undetermined]",
    "no matching records",
    "bulunmamaktadır",
    "bulunmuyor",
    "bulunamadı",
    "yer almıyor",
    "yer almamaktadır",
    "bilgi yok",
    "no information",
    "don't have information",
    "do not have information",
    "don't have access",
    "do not have access",
    "bilgim yok",
    "bilgiye sahip değilim",
    "erişimim yok",
    "not mentioned",
    "does not contain",
)


def normalize_text(text: str) -> str:
    """Case-fold (Turkish-aware for İ) and drop thousands separators, e.g. '15.000 TL' -> '15000 tl'."""
    text = text.replace("İ", "i").casefold().replace("̇", "")
    text = re.sub(r"(?<=\d)[.,](?=\d{3}(?!\d))", "", text)
    return re.sub(r"\s+", " ", text)


def _alternative_found(normalized_answer: str, alternative: str) -> bool:
    needle = normalize_text(alternative)
    if not needle:
        return False
    if needle.replace(" ", "").isdigit():
        # Numbers must not be part of a longer number: '2' must not match '2026' or '12'
        return re.search(rf"(?<![\d]){re.escape(needle)}(?![\d])", normalized_answer) is not None
    return needle in normalized_answer


def fact_found(answer: str, fact: Fact) -> bool:
    """A fact is a string or a list of alternative spellings; any alternative counts."""
    alternatives = [fact] if isinstance(fact, str) else list(fact)
    normalized = normalize_text(answer)
    return any(_alternative_found(normalized, alt) for alt in alternatives)


def fact_recall(answer: str, facts: Sequence[Fact]) -> Optional[float]:
    """Fraction of expected facts present in the answer, or None when the case defines no facts."""
    if not facts:
        return None
    return sum(fact_found(answer, fact) for fact in facts) / len(facts)


def is_refusal(answer: str) -> bool:
    normalized = normalize_text(answer)
    return any(normalize_text(marker) in normalized for marker in REFUSAL_MARKERS)


def first_relevant_rank(ranked_sources: Sequence[str], expected_sources: Iterable[str]) -> Optional[int]:
    """1-based rank of the first chunk coming from an expected source, or None if absent."""
    expected = set(expected_sources)
    for rank, source in enumerate(ranked_sources, start=1):
        if source in expected:
            return rank
    return None


def select_like_production(
    candidates: Sequence[Dict[str, Any]],
    min_similarity: float,
    pool_size: int,
    top_n: int,
    min_reranker_score: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Reproduce RAGEngine.search() selection from fully scored candidates.

    candidates: dicts with 'similarity' and 'reranker_score'. Production takes the `pool_size` most
    similar chunks, drops those below `min_similarity`, reranks the rest, drops those below
    `min_reranker_score` (None = no reranker threshold) and keeps `top_n`.
    """
    pool = sorted(candidates, key=lambda c: c["similarity"], reverse=True)[:pool_size]
    kept = [c for c in pool if c["similarity"] >= min_similarity]
    if min_reranker_score is not None:
        kept = [c for c in kept if c["reranker_score"] >= min_reranker_score]
    return sorted(kept, key=lambda c: c["reranker_score"], reverse=True)[:top_n]


def threshold_sweep(
    relevant_similarities: Sequence[Optional[float]],
    out_of_scope_similarities: Sequence[float],
    thresholds: Sequence[float],
) -> Dict[str, Any]:
    """Trade-off of the similarity threshold between keeping relevant chunks and rejecting off-topic questions.

    relevant_similarities: per in-scope question, the best similarity of a chunk from an expected source
        (None if no such chunk exists).
    out_of_scope_similarities: per out-of-scope question, the best similarity of any chunk.

    The recommendation keeps the highest achievable in-scope recall and, among those thresholds, maximizes
    the out-of-scope rejection rate; ties are broken by taking the middle of the tied range for margin.
    """
    rows = []
    for t in thresholds:
        in_scope = [s is not None and s >= t for s in relevant_similarities]
        rejected = [s < t for s in out_of_scope_similarities]
        rows.append(
            {
                "threshold": round(t, 4),
                "in_scope_recall": _ratio(in_scope),
                "out_of_scope_rejection": _ratio(rejected),
            }
        )

    recommended = None
    if rows:
        best_recall = max(r["in_scope_recall"] or 0.0 for r in rows)
        eligible = [r for r in rows if (r["in_scope_recall"] or 0.0) == best_recall]
        best_rejection = max(r["out_of_scope_rejection"] or 0.0 for r in eligible)
        tied = [r for r in eligible if (r["out_of_scope_rejection"] or 0.0) == best_rejection]
        recommended = tied[len(tied) // 2]["threshold"]

    return {"rows": rows, "recommended_threshold": recommended}


def frange(start: float, stop: float, step: float) -> List[float]:
    count = int(math.floor((stop - start) / step + 1e-9)) + 1
    return [round(start + i * step, 4) for i in range(count)]


def _ratio(flags: Sequence[bool]) -> Optional[float]:
    return sum(flags) / len(flags) if flags else None


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def load_dataset(path: str) -> List[Dict[str, Any]]:
    """Load and validate a JSONL dataset (one case per line, blank lines and '#' comments ignored)."""
    cases = []
    seen_ids = set()
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            case = json.loads(line)
            for key in ("id", "category", "question", "expected_agent"):
                if key not in case:
                    raise ValueError(f"{path}:{line_no}: missing required field '{key}'")
            if case["category"] not in CATEGORIES:
                raise ValueError(f"{path}:{line_no}: unknown category '{case['category']}'")
            if case["id"] in seen_ids:
                raise ValueError(f"{path}:{line_no}: duplicate id '{case['id']}'")
            seen_ids.add(case["id"])
            case.setdefault("expected_sources", [])
            case.setdefault("expected_facts", [])
            case.setdefault("expect_refusal", case["category"] == "out_of_scope")
            if isinstance(case["expected_agent"], str):
                case["expected_agent"] = [case["expected_agent"]]
            cases.append(case)
    return cases


def flatten_summary(summary: Dict[str, Any], prefix: str = "") -> Dict[str, float]:
    """Flatten nested summary metrics into {'retrieval.hit_rate': 0.9, ...} for comparisons."""
    flat: Dict[str, float] = {}
    for key, value in summary.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten_summary(value, prefix=f"{name}."))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            flat[name] = float(value)
    return flat


def compare_summaries(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Metric-by-metric difference between two report summaries (metrics present in both)."""
    cur, base = flatten_summary(current), flatten_summary(baseline)
    return [
        {"metric": name, "baseline": base[name], "current": cur[name], "delta": cur[name] - base[name]}
        for name in sorted(cur.keys() & base.keys())
    ]
