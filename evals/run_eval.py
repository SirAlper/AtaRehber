"""Evaluation harness: measures retrieval, routing and end-to-end answer quality on a labeled dataset.

Usage (from the repository root):
    python -m evals.run_eval                               # retrieval only (embedding + reranker, no LLM)
    python -m evals.run_eval --stages all                  # retrieval + routing + end-to-end (needs Ollama)
    python -m evals.run_eval --compare evals/results/<previous report>.json

Settings under test are read from the environment like the application itself, e.g.
    RAG_MIN_SIMILARITY=0.4 RERANKER_TOP_N=5 CHUNK_SIZE=400 python -m evals.run_eval

Everything runs in a temporary directory: an isolated vector store built from the corpus and a fresh
sample database. Your data/ and vector_db/ folders are never read or modified.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from evals import metrics

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVALS_DIR, "dataset.jsonl")
DEFAULT_CORPUS = os.path.join(EVALS_DIR, "corpus")
DEFAULT_RESULTS_DIR = os.path.join(EVALS_DIR, "results")
STAGES = ("retrieval", "routing", "e2e")
# RAGEngine.search() default candidate pool (n_results)
PRODUCTION_POOL_SIZE = 10
# Cross-encoder scores are sigmoid outputs clustered near 0 and 1, so the grid is denser at the low end
RERANKER_SWEEP_THRESHOLDS = [0.0, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5]


def _isolate_environment(work_dir: str) -> None:
    """Must run before anything from `src` is imported: configuration is read at import time."""
    os.environ["DATA_DIR"] = os.path.join(work_dir, "data")
    os.environ.setdefault("LOG_FILE", os.path.join(work_dir, "eval.log"))
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.makedirs(os.environ["DATA_DIR"], exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, cwd=EVALS_DIR
        ).stdout.strip()
    except Exception:
        return "unknown"


def _fmt(value: Any, pct: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value * 100:5.1f}%" if pct else f"{value:.3f}"


# ─────────────────────────────── Retrieval ───────────────────────────────


def build_engine(corpus_dir: str, work_dir: str):
    from src.rag.document_loader import DocumentLoader
    from src.rag.rag_engine import RAGEngine

    engine = RAGEngine(vector_db_path=os.path.join(work_dir, "vector_db"))
    chunks, ids, metadatas = DocumentLoader(corpus_dir).load_and_chunk_all()
    if not chunks:
        raise SystemExit(f"No supported documents found in corpus: {corpus_dir}")
    engine.add_documents(chunks, ids, metadatas)
    return engine, len(chunks)


def run_retrieval(engine, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    from src.core.config import RAG_MIN_RERANKER_SCORE, RAG_MIN_SIMILARITY, RERANKER_TOP_N
    from src.rag.rag_engine import distance_to_similarity

    total_chunks = engine.collection.count()
    records = []
    for case in cases:
        if case["category"] not in metrics.RETRIEVAL_CATEGORIES:
            continue
        # Score every chunk once; production selection is then replayed without extra model calls
        result = engine.search(
            case["question"], n_results=total_chunks, min_similarity=-2.0, top_n=total_chunks, min_reranker_score=-1.0
        )
        candidates = [
            {
                "source": s["source"],
                "chunk_index": s["chunk_index"],
                "similarity": round(distance_to_similarity(s["distance"], engine.distance_space), 4),
                "reranker_score": s["reranker_score"],
            }
            for s in result["sources"]
        ]
        selected = metrics.select_like_production(
            candidates,
            RAG_MIN_SIMILARITY,
            pool_size=PRODUCTION_POOL_SIZE,
            top_n=RERANKER_TOP_N,
            min_reranker_score=RAG_MIN_RERANKER_SCORE,
        )
        unfiltered = metrics.select_like_production(
            candidates, -2.0, pool_size=PRODUCTION_POOL_SIZE, top_n=RERANKER_TOP_N
        )
        expected = case["expected_sources"]
        relevant = [c for c in candidates if c["source"] in expected]
        rank = metrics.first_relevant_rank([c["source"] for c in selected], expected)
        records.append(
            {
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "expected_sources": expected,
                "retrieved": [f"{c['source']}#{c['chunk_index']}" for c in selected],
                "rank": rank,
                "hit": rank is not None,
                "hit_without_threshold": metrics.first_relevant_rank([c["source"] for c in unfiltered], expected)
                is not None,
                "relevant_similarity": max((c["similarity"] for c in relevant), default=None),
                "max_similarity": max((c["similarity"] for c in candidates), default=None),
                "relevant_reranker_score": max((c["reranker_score"] for c in relevant), default=None),
                "max_reranker_score": max((c["reranker_score"] for c in candidates), default=None),
                "rejected": not selected,
            }
        )

    in_scope = [r for r in records if r["expected_sources"]]
    out_of_scope = [r for r in records if r["category"] == "out_of_scope"]
    sweep = metrics.threshold_sweep(
        [r["relevant_similarity"] for r in in_scope],
        [r["max_similarity"] for r in out_of_scope if r["max_similarity"] is not None],
        metrics.frange(0.20, 0.70, 0.025),
    )
    # Same trade-off for the cross-encoder score (RAG_MIN_RERANKER_SCORE)
    reranker_sweep = metrics.threshold_sweep(
        [r["relevant_reranker_score"] for r in in_scope],
        [r["max_reranker_score"] for r in out_of_scope if r["max_reranker_score"] is not None],
        RERANKER_SWEEP_THRESHOLDS,
    )
    summary = {
        "in_scope_cases": len(in_scope),
        "out_of_scope_cases": len(out_of_scope),
        "hit_rate": metrics.mean(float(r["hit"]) for r in in_scope),
        "mrr": metrics.mean(1.0 / r["rank"] if r["rank"] else 0.0 for r in in_scope),
        "hit_rate_without_threshold": metrics.mean(float(r["hit_without_threshold"]) for r in in_scope),
        "out_of_scope_rejection": metrics.mean(float(r["rejected"]) for r in out_of_scope),
        "min_similarity": RAG_MIN_SIMILARITY,
        "min_reranker_score": RAG_MIN_RERANKER_SCORE,
        "top_n": RERANKER_TOP_N,
        "recommended_min_similarity": sweep["recommended_threshold"],
        "recommended_min_reranker_score": reranker_sweep["recommended_threshold"],
    }
    return {
        "summary": summary,
        "cases": records,
        "threshold_sweep": sweep["rows"],
        "reranker_threshold_sweep": reranker_sweep["rows"],
    }


def print_retrieval(section: Dict[str, Any]) -> None:
    s = section["summary"]
    print("\n== Retrieval ==")
    print(f"  in-scope questions            : {s['in_scope_cases']}")
    print(f"  hit rate @top_n={s['top_n']}            : {_fmt(s['hit_rate'])}")
    print(f"  MRR                           : {_fmt(s['mrr'], pct=False)}")
    print(f"  hit rate without threshold    : {_fmt(s['hit_rate_without_threshold'])}")
    print(
        f"  out-of-scope rejected         : {_fmt(s['out_of_scope_rejection'])}  ({s['out_of_scope_cases']} questions)"
    )
    print(f"  RAG_MIN_SIMILARITY current    : {s['min_similarity']}")
    print(f"  RAG_MIN_SIMILARITY suggested  : {s['recommended_min_similarity']}")
    print(f"  RAG_MIN_RERANKER_SCORE current: {s['min_reranker_score']}")
    print(f"  RAG_MIN_RERANKER_SCORE suggested: {s['recommended_min_reranker_score']}")
    misses = [r for r in section["cases"] if r["expected_sources"] and not r["hit"]]
    for r in misses:
        reason = "dropped by threshold" if r["hit_without_threshold"] else "ranked out"
        print(f"  MISS {r['id']:<12} ({reason}; relevant sim={r['relevant_similarity']}) -> {r['retrieved']}")
    leaks = [r for r in section["cases"] if r["category"] == "out_of_scope" and not r["rejected"]]
    for r in leaks:
        print(
            f"  LEAK {r['id']:<12} (max sim={r['max_similarity']}, max rerank={r['max_reranker_score']})"
            f" -> {r['retrieved']}"
        )
    print("  similarity threshold sweep (in-scope recall / out-of-scope rejection):")
    for row in section["threshold_sweep"]:
        marker = " <- current" if abs(row["threshold"] - s["min_similarity"]) < 1e-6 else ""
        print(
            f"    {row['threshold']:.3f}  {_fmt(row['in_scope_recall'])} / {_fmt(row['out_of_scope_rejection'])}{marker}"
        )
    print("  reranker score sweep (in-scope recall / out-of-scope rejection):")
    for row in section["reranker_threshold_sweep"]:
        marker = " <- current" if abs(row["threshold"] - s["min_reranker_score"]) < 1e-9 else ""
        print(
            f"    {row['threshold']:.3f}  {_fmt(row['in_scope_recall'])} / {_fmt(row['out_of_scope_rejection'])}{marker}"
        )


# ─────────────────────────────── Agents ───────────────────────────────


def build_registry(engine, work_dir: str):
    from src.agent.multi_agent.registry import AgentRegistry
    from src.agent.multi_agent.sub_agents.compliance_agent import ComplianceAuditorAgent
    from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
    from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
    from src.connectors.db_connector import DatabaseConnector, create_sample_sqlite_db

    db_path = create_sample_sqlite_db(os.path.join(work_dir, "sample_enterprise.db"))
    connector = DatabaseConnector(database_url=f"sqlite:///{db_path}", allowed_tables=[])

    registry = AgentRegistry()
    registry.register(DocumentRagAgent(rag_engine=engine))
    registry.register(DatabaseAgent(db_connector=connector))
    registry.register(ComplianceAuditorAgent(rag_engine=engine))
    return registry


def run_routing(chat_model, registry, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    from src.agent.multi_agent.supervisor import SupervisorAgent

    supervisor = SupervisorAgent(chat_model=chat_model, registry=registry)
    records = []
    for case in cases:
        decision = supervisor.route({"question": case["question"], "chat_history": [], "agent_trace": []})
        predicted = decision.get("next_agent") or "finish"
        predicted = "supervisor" if predicted == "finish" else predicted
        ok = predicted in case["expected_agent"]
        records.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected": case["expected_agent"],
                "predicted": predicted,
                "correct": ok,
            }
        )
        print(f"  [{'ok' if ok else 'XX'}] {case['id']:<12} -> {predicted}")

    summary = {"accuracy": metrics.mean(float(r["correct"]) for r in records), "by_category": {}}
    for category in metrics.CATEGORIES:
        rows = [r for r in records if r["category"] == category]
        if rows:
            summary["by_category"][category] = metrics.mean(float(r["correct"]) for r in rows)
    return {"summary": summary, "cases": records}


def run_e2e(chat_model, registry, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    from langgraph.checkpoint.memory import MemorySaver

    from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
    from src.agent.nodes import is_grade_passed
    from src.agent.prompts import FALLBACK_RESPONSE, NO_CONTEXT_RESPONSE

    orchestrator = MultiAgentOrchestrator(chat_model=chat_model, registry=registry, checkpointer=MemorySaver())
    records = []
    for case in cases:
        start = time.perf_counter()
        try:
            result = orchestrator.query(case["question"])
            error = None
        except Exception as e:  # keep evaluating the remaining cases
            result, error = {"answer": "", "sources": [], "active_agent": "error"}, f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - start

        answer = result.get("answer", "")
        returned_sources = {s.get("source") for s in result.get("sources", [])}
        refused = answer.strip() in (NO_CONTEXT_RESPONSE, FALLBACK_RESPONSE) or metrics.is_refusal(answer)
        recall = metrics.fact_recall(answer, case["expected_facts"])
        grade = result.get("hallucination_grade", "")
        record = {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "answer": answer,
            "agent": result.get("active_agent"),
            "agent_correct": result.get("active_agent") in case["expected_agent"],
            "fact_recall": recall,
            "answer_correct": recall == 1.0 if recall is not None else None,
            "source_hit": bool(returned_sources & set(case["expected_sources"])) if case["expected_sources"] else None,
            "refused": refused,
            "hallucination_grade": grade,
            "grounded": is_grade_passed(grade) if grade else None,
            "latency_s": round(latency, 2),
            "error": error,
        }
        records.append(record)
        if case["expect_refusal"]:
            passed = refused
        elif record["answer_correct"] is not None:
            passed = record["answer_correct"]
        else:  # e.g. greetings: no facts to check, only the routing
            passed = record["agent_correct"]
        status = "ok" if passed else "XX"
        print(f"  [{status}] {case['id']:<12} {latency:6.1f}s  agent={record['agent']}  facts={_fmt(recall)}")

    def rate(rows, key):
        return metrics.mean(float(r[key]) if r[key] is not None else None for r in rows)

    answerable = [r for r, c in zip(records, cases) if not c["expect_refusal"] and c["expected_facts"]]
    unanswerable = [r for r, c in zip(records, cases) if c["expect_refusal"]]
    latencies = [r["latency_s"] for r in records]
    summary = {
        "agent_accuracy": rate(records, "agent_correct"),
        "answer_accuracy": rate(answerable, "answer_correct"),
        "fact_recall": metrics.mean(r["fact_recall"] for r in answerable),
        "source_hit_rate": rate(records, "source_hit"),
        "grounded_rate": rate(records, "grounded"),
        # Answerable questions the system refused (too strict) vs. unanswerable questions it answered (hallucination risk)
        "false_refusal_rate": rate(answerable, "refused"),
        "out_of_scope_refusal_rate": rate(unanswerable, "refused"),
        "errors": sum(1 for r in records if r["error"]),
        "latency_p50_s": metrics.percentile(latencies, 50),
        "latency_p95_s": metrics.percentile(latencies, 95),
        "answer_accuracy_by_category": {},
    }
    for category in metrics.CATEGORIES:
        rows = [r for r in answerable if r["category"] == category]
        if rows:
            summary["answer_accuracy_by_category"][category] = rate(rows, "answer_correct")
    return {"summary": summary, "cases": records}


def print_e2e(section: Dict[str, Any]) -> None:
    s = section["summary"]
    print("\n== End-to-end ==")
    print(f"  agent accuracy                : {_fmt(s['agent_accuracy'])}")
    print(f"  answer accuracy (all facts)   : {_fmt(s['answer_accuracy'])}")
    for category, value in s["answer_accuracy_by_category"].items():
        print(f"    {category:<27} : {_fmt(value)}")
    print(f"  fact recall                   : {_fmt(s['fact_recall'])}")
    print(f"  source hit rate               : {_fmt(s['source_hit_rate'])}")
    print(f"  grounded (Self-RAG passed)    : {_fmt(s['grounded_rate'])}")
    print(f"  false refusals                : {_fmt(s['false_refusal_rate'])}")
    print(f"  out-of-scope refused          : {_fmt(s['out_of_scope_refusal_rate'])}")
    print(f"  latency p50 / p95             : {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    if s["errors"]:
        print(f"  ERRORS                        : {s['errors']}")


# ─────────────────────────────── Main ───────────────────────────────


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate retrieval, routing and answer quality.")
    parser.add_argument(
        "--stages", default="retrieval", help=f"Comma-separated subset of {', '.join(STAGES)}, or 'all'."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS, help="Directory of PDF/DOCX/TXT files to index.")
    parser.add_argument("--category", action="append", choices=metrics.CATEGORIES, help="Only these categories.")
    parser.add_argument("--ids", help="Comma-separated case ids to run.")
    parser.add_argument("--out", default=DEFAULT_RESULTS_DIR, help="Directory for the JSON report.")
    parser.add_argument("--compare", help="Previous JSON report to compare against.")
    parser.add_argument("--keep-workdir", action="store_true", help="Keep the temporary vector store and DB.")
    args = parser.parse_args(argv)

    stages = STAGES if args.stages == "all" else tuple(s.strip() for s in args.stages.split(",") if s.strip())
    unknown = set(stages) - set(STAGES)
    if unknown:
        parser.error(f"unknown stage(s): {', '.join(sorted(unknown))}")
    args.stages = stages
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # Line buffering keeps progress visible when output is redirected to a file
        sys.stdout.reconfigure(errors="replace", line_buffering=True)

    cases = metrics.load_dataset(args.dataset)
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("No cases selected.")
        return 1

    work_dir = tempfile.mkdtemp(prefix="olra_eval_")
    _isolate_environment(work_dir)
    try:
        from src.core import config

        report: Dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_commit(),
            "dataset": os.path.relpath(args.dataset),
            "corpus": os.path.relpath(args.corpus),
            "stages": list(args.stages),
            "case_count": len(cases),
            "config": {
                "embedding_model": os.path.basename(config.EMBEDDING_MODEL_NAME),
                "reranker_model": os.path.basename(config.RERANKER_MODEL_NAME),
                "llm_backend": "ollama",
                "llm_model": config.OLLAMA_MODEL,
                "ollama_num_ctx": config.OLLAMA_NUM_CTX,
                "rag_min_similarity": config.RAG_MIN_SIMILARITY,
                "rag_min_reranker_score": config.RAG_MIN_RERANKER_SCORE,
                "reranker_top_n": config.RERANKER_TOP_N,
                "chunk_size": config.CHUNK_SIZE,
                "chunk_overlap": config.CHUNK_OVERLAP,
            },
            "summary": {},
            "details": {},
        }
        print(f"Evaluating {len(cases)} cases, stages: {', '.join(args.stages)}")

        if "routing" in args.stages or "e2e" in args.stages:
            from src.agent.llm import check_ollama

            # Fail fast instead of recording an error for every question
            llm_problem = check_ollama()
            if llm_problem:
                print(f"LLM not available: {llm_problem}")
                return 1
            print(f"LLM: {config.OLLAMA_MODEL} via Ollama at {config.OLLAMA_BASE_URL}")

        # Routing only needs the agents' descriptions, not the vector store
        engine = None
        if "retrieval" in args.stages or "e2e" in args.stages:
            print("Indexing corpus...")
            engine, chunk_count = build_engine(args.corpus, work_dir)
            report["config"]["corpus_chunks"] = chunk_count

        if "retrieval" in args.stages:
            section = run_retrieval(engine, cases)
            report["summary"]["retrieval"] = section["summary"]
            report["details"]["retrieval"] = section
            print_retrieval(section)

        if "routing" in args.stages or "e2e" in args.stages:
            from src.agent.llm import create_chat_model

            chat_model = create_chat_model()
            registry = build_registry(engine, work_dir)

            if "routing" in args.stages:
                print("\n== Routing ==")
                section = run_routing(chat_model, registry, cases)
                report["summary"]["routing"] = section["summary"]
                report["details"]["routing"] = section
                print(f"  accuracy: {_fmt(section['summary']['accuracy'])}")
                for category, value in section["summary"]["by_category"].items():
                    print(f"    {category:<12}: {_fmt(value)}")

            if "e2e" in args.stages:
                print("\n== Running end-to-end ==")
                section = run_e2e(chat_model, registry, cases)
                report["summary"]["e2e"] = section["summary"]
                report["details"]["e2e"] = section
                print_e2e(section)

        os.makedirs(args.out, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(args.out, f"report_{stamp}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport written to {os.path.relpath(report_path)}")

        if args.compare:
            with open(args.compare, encoding="utf-8") as f:
                baseline = json.load(f)
            print(f"\n== Compared with {os.path.relpath(args.compare)} ==")
            for row in metrics.compare_summaries(report["summary"], baseline.get("summary", {})):
                if abs(row["delta"]) > 1e-9:
                    print(
                        f"  {row['metric']:<55} {row['baseline']:8.3f} -> {row['current']:8.3f} ({row['delta']:+.3f})"
                    )
        return 0
    finally:
        if args.keep_workdir:
            print(f"Work directory kept at {work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
