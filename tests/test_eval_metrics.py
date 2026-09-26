import json

import pytest

from evals import metrics
from evals.run_eval import DEFAULT_CORPUS, DEFAULT_DATASET, parse_args


def test_numeric_facts_do_not_match_inside_longer_numbers():
    assert metrics.fact_found("En az 2 kıdemli mühendis onayı gerekir.", "2")
    assert not metrics.fact_found("KOD: ENG-DEV-2026", "2")
    assert not metrics.fact_found("12 gün", "2")


def test_thousands_separators_are_normalized():
    assert metrics.fact_found("Yıllık 15.000 TL bütçe verilir.", "15000")
    assert metrics.fact_found("Toplam 207,600 TL", "207600")
    # A decimal part is not a thousands group
    assert not metrics.fact_found("85000.5", "850005")


def test_turkish_case_folding_and_alternatives():
    assert metrics.fact_found("İHLAL tespit edildi", "ihlal")
    assert metrics.fact_found("Verdict: [VIOLATION / PROHIBITED]", ["İHLAL", "violation"])
    assert not metrics.fact_found("Uygun", ["İHLAL", "violation"])


def test_fact_recall():
    assert metrics.fact_recall("Salı ve Perşembe", [["Salı", "Tuesday"], ["Perşembe"]]) == 1.0
    assert metrics.fact_recall("Sadece Salı", [["Salı"], ["Perşembe"]]) == 0.5
    assert metrics.fact_recall("anything", []) is None


def test_refusal_detection():
    assert metrics.is_refusal("This information is not found in company documents.")
    assert metrics.is_refusal("Bu bilgi dokümanlarda yer almıyor.")
    assert not metrics.is_refusal("Şifreler en az 14 karakter olmalıdır.")


def test_first_relevant_rank():
    assert metrics.first_relevant_rank(["a.txt", "b.txt", "c.txt"], ["c.txt", "b.txt"]) == 2
    assert metrics.first_relevant_rank(["a.txt"], ["b.txt"]) is None


def test_select_like_production_applies_pool_threshold_and_rerank():
    candidates = [
        {"id": "high-sim-low-rerank", "similarity": 0.9, "reranker_score": 0.1},
        {"id": "mid", "similarity": 0.6, "reranker_score": 0.9},
        {"id": "third", "similarity": 0.5, "reranker_score": 0.95},
    ]
    # Pool: only the 2 most similar chunks reach the reranker, which then reorders them
    selected = metrics.select_like_production(candidates, min_similarity=0.0, pool_size=2, top_n=3)
    assert [c["id"] for c in selected] == ["mid", "high-sim-low-rerank"]
    # Threshold: 'third' is in the pool but below min_similarity
    selected = metrics.select_like_production(candidates, min_similarity=0.55, pool_size=3, top_n=3)
    assert [c["id"] for c in selected] == ["mid", "high-sim-low-rerank"]
    # top_n
    selected = metrics.select_like_production(candidates, min_similarity=0.0, pool_size=3, top_n=1)
    assert [c["id"] for c in selected] == ["third"]


def test_threshold_sweep_keeps_recall_then_maximizes_rejection():
    sweep = metrics.threshold_sweep(
        relevant_similarities=[0.6, 0.7, None],
        out_of_scope_similarities=[0.4, 0.5],
        thresholds=[0.3, 0.45, 0.55, 0.65],
    )
    by_threshold = {r["threshold"]: r for r in sweep["rows"]}
    assert by_threshold[0.3]["in_scope_recall"] == pytest.approx(2 / 3)
    assert by_threshold[0.55]["out_of_scope_rejection"] == 1.0
    # 0.55 keeps the best recall (2/3) and rejects both off-topic questions; 0.65 would lose recall
    assert sweep["recommended_threshold"] == 0.55


def test_frange_and_percentile():
    assert metrics.frange(0.2, 0.3, 0.05) == [0.2, 0.25, 0.3]
    assert metrics.percentile([5, 1, 3, 2, 4], 50) == 3
    assert metrics.percentile([], 95) is None


def test_compare_summaries_reports_nested_deltas():
    rows = metrics.compare_summaries(
        {"retrieval": {"hit_rate": 0.9, "top_n": 3}, "e2e": {"by": {"document": 0.5}}},
        {"retrieval": {"hit_rate": 0.8, "top_n": 3}, "routing": {"accuracy": 1.0}},
    )
    assert rows == [
        {"metric": "retrieval.hit_rate", "baseline": 0.8, "current": 0.9, "delta": pytest.approx(0.1)},
        {"metric": "retrieval.top_n", "baseline": 3.0, "current": 3.0, "delta": 0.0},
    ]


def test_load_dataset_validates_cases(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "# comment\n"
        + json.dumps({"id": "a", "category": "document", "question": "q", "expected_agent": "doc_agent"})
        + "\n\n"
        + json.dumps({"id": "b", "category": "out_of_scope", "question": "q", "expected_agent": ["doc_agent"]})
        + "\n",
        encoding="utf-8",
    )
    cases = metrics.load_dataset(str(path))
    assert cases[0]["expected_agent"] == ["doc_agent"]
    assert cases[0]["expect_refusal"] is False
    assert cases[1]["expect_refusal"] is True

    path.write_text(
        json.dumps({"id": "a", "category": "unknown", "question": "q", "expected_agent": "x"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown category"):
        metrics.load_dataset(str(path))


def test_bundled_dataset_is_valid_and_references_corpus_files():
    import os

    cases = metrics.load_dataset(DEFAULT_DATASET)
    corpus_files = set(os.listdir(DEFAULT_CORPUS))
    assert len(cases) >= 30
    for case in cases:
        assert set(case["expected_sources"]) <= corpus_files, case["id"]
        if case["category"] in ("document", "compliance"):
            assert case["expected_sources"], f"{case['id']} needs expected_sources for retrieval scoring"


def test_parse_args_stages():
    assert parse_args(["--stages", "all"]).stages == ("retrieval", "routing", "e2e")
    assert parse_args([]).stages == ("retrieval",)
    with pytest.raises(SystemExit):
        parse_args(["--stages", "retrieval,bogus"])
