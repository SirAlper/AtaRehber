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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from evals import metrics

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVALS_DIR, "dataset.jsonl")
DEFAULT_CORPUS = os.path.join(EVALS_DIR, "corpus")
DEFAULT_RESULTS_DIR = os.path.join(EVALS_DIR, "results")
DEFAULT_INDEX_CACHE = os.path.join(EVALS_DIR, ".cache")
# Candidates (by vector similarity) the retrieval stage scores with the cross-encoder. Production uses 10; a larger
# pool is enough for the threshold sweeps and keeps large corpora (a whole law) fast.
DEFAULT_RETRIEVAL_POOL = 50
STAGES = ("retrieval", "routing", "e2e")
# Stages run only when named: "grader" needs the answer-check dataset (evals/build_grader_dataset.py), "agents"
# measures plans, combined answers, and questions back (evals/dataset_agents.jsonl)
EXTRA_STAGES = ("grader", "agents")
DEFAULT_GRADER_DATASET = os.path.join(EVALS_DIR, "grader_dataset_university.jsonl")
DEFAULT_AGENTS_DATASET = os.path.join(EVALS_DIR, "dataset_agents.jsonl")
EVAL_USER = {"username": "eval", "role": "admin", "groups": []}
# RAGEngine.search() default candidate pool (n_results)
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


def _clock(seconds: float) -> str:
    minutes, seconds = divmod(int(round(seconds)), 60)
    return f"{minutes}:{seconds:02d}"


class Progress:
    """Says which case of a stage is running, and after each one how far the stage is and how long the rest takes
    (from the mean time per case so far)."""

    def __init__(self, stage: str, total: int):
        self.stage, self.total, self.done = stage, total, 0
        self.started = time.perf_counter()

    def begin(self, case_id: str) -> None:
        """Printed before the case runs, so a slow or hanging case is visible by name."""
        self.done += 1
        print(f"  > {self.stage} {self.done}/{self.total}: {case_id} ...")

    def status(self) -> str:
        """Appended to the line that reports the finished case."""
        elapsed = time.perf_counter() - self.started
        left = elapsed / self.done * (self.total - self.done) if self.done else 0.0
        return f"| {self.done}/{self.total}, {_clock(elapsed)} elapsed, about {_clock(left)} left"


def index_cache_key(corpus_dir: str) -> str:
    """Changes whenever the corpus, the chunking settings, the loader code, or the embedding model change."""
    from src.core import config
    from src.rag import document_loader

    digest = hashlib.sha256()
    for name in sorted(os.listdir(corpus_dir)):
        path = os.path.join(corpus_dir, name)
        if os.path.isfile(path):
            digest.update(name.encode())
            with open(path, "rb") as f:
                digest.update(f.read())
    with open(document_loader.__file__, "rb") as f:
        digest.update(f.read())
    digest.update(
        f"{config.CHUNK_SIZE}|{config.ARTICLE_CHUNK_SIZE}|{config.CHUNK_OVERLAP}|{config.EMBEDDING_MODEL_NAME}".encode()
    )
    return digest.hexdigest()[:16]


def build_engine(corpus_dir: str, work_dir: str, cache_dir: Optional[str] = None):
    """Index the corpus into a fresh vector store, or copy a cached index built from the same inputs."""
    from src.rag.document_loader import DocumentLoader
    from src.rag.rag_engine import RAGEngine

    vector_db = os.path.join(work_dir, "vector_db")
    cached = os.path.join(cache_dir, f"index_{index_cache_key(corpus_dir)}") if cache_dir else None
    if cached and os.path.isdir(cached):
        shutil.copytree(cached, vector_db)
        engine = RAGEngine(vector_db_path=vector_db)
        print(f"Using cached index {os.path.relpath(cached)}")
        return engine, engine.collection.count()

    engine = RAGEngine(vector_db_path=vector_db)
    chunks, ids, metadatas = DocumentLoader(corpus_dir).load_and_chunk_all()
    if not chunks:
        raise SystemExit(f"No supported documents found in corpus: {corpus_dir}")
    engine.add_documents(chunks, ids, metadatas)
    if cached:
        shutil.copytree(vector_db, cached)
    return engine, len(chunks)


# Candidate pools compared in the retrieval stage (RAG_CANDIDATE_POOL)
POOL_SWEEP = (10, 15, 20, 30)


def run_retrieval(engine, cases: List[Dict[str, Any]], pool: int = DEFAULT_RETRIEVAL_POOL) -> Dict[str, Any]:
    from src.core.config import RAG_CANDIDATE_POOL, RAG_MIN_RERANKER_SCORE, RAG_MIN_SIMILARITY, RERANKER_TOP_N
    from src.rag.rag_engine import distance_to_similarity

    pool = min(max(pool, RAG_CANDIDATE_POOL, *POOL_SWEEP), engine.collection.count())
    sweep_pools = [size for size in POOL_SWEEP if size <= pool]
    records = []
    cases = [case for case in cases if case["category"] in metrics.RETRIEVAL_CATEGORIES]
    progress = Progress("retrieval", len(cases))
    for case in cases:
        progress.begin(case["id"])
        # Score the candidate pool once; production selection is then replayed without extra model calls
        result = engine.search(
            case["question"], n_results=pool, min_similarity=-2.0, top_n=pool, min_reranker_score=-1.0
        )
        candidates = [
            {
                "source": s["source"],
                "chunk_index": s["chunk_index"],
                "similarity": round(distance_to_similarity(s["distance"], engine.distance_space), 4),
                "reranker_score": s["reranker_score"],
                "content": s.get("content", ""),
            }
            for s in result["sources"]
        ]

        def select(pool_size: int, min_similarity: float = RAG_MIN_SIMILARITY, min_score=RAG_MIN_RERANKER_SCORE):
            return metrics.select_like_production(
                candidates, min_similarity, pool_size=pool_size, top_n=RERANKER_TOP_N, min_reranker_score=min_score
            )

        selected = select(RAG_CANDIDATE_POOL)
        unfiltered = select(RAG_CANDIDATE_POOL, -2.0, None)
        facts = case.get("expected_facts") or []

        def context_recall(chunks) -> Optional[float]:
            # Whether the facts of the expected answer are in the chunks given to the model: a chunk-level check
            # (the right document can still be the wrong article)
            return metrics.fact_recall("\n".join(c["content"] for c in chunks), facts) if facts else None

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
                "context_fact_recall": context_recall(selected),
                "pool_sweep": {
                    str(size): {
                        "hit": metrics.first_relevant_rank([c["source"] for c in select(size)], expected) is not None,
                        "context_fact_recall": context_recall(select(size)),
                    }
                    for size in sweep_pools
                },
            }
        )
        if expected:
            outcome = f"[{'ok' if rank else 'XX'}] {case['id']:<12} rank={rank or '-'}"
        else:
            outcome = f"[{'ok' if not selected else 'XX'}] {case['id']:<12} off-topic, {len(selected)} chunks pass"
        print(f"  {outcome}  {progress.status()}")

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
        # Share of the expected facts that are in the selected chunks (chunk level, see context_recall)
        "context_fact_recall": metrics.mean(r["context_fact_recall"] for r in in_scope),
        "candidate_pool": RAG_CANDIDATE_POOL,
        "min_similarity": RAG_MIN_SIMILARITY,
        "min_reranker_score": RAG_MIN_RERANKER_SCORE,
        "top_n": RERANKER_TOP_N,
        "recommended_min_similarity": sweep["recommended_threshold"],
        "recommended_min_reranker_score": reranker_sweep["recommended_threshold"],
    }
    pool_rows = [
        {
            "pool": size,
            "hit_rate": metrics.mean(float(r["pool_sweep"][str(size)]["hit"]) for r in in_scope),
            "context_fact_recall": metrics.mean(r["pool_sweep"][str(size)]["context_fact_recall"] for r in in_scope),
        }
        for size in sweep_pools
    ]
    return {
        "summary": summary,
        "cases": records,
        "pool_sweep": pool_rows,
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
    print(f"  expected facts in context     : {_fmt(s['context_fact_recall'])}  (pool {s['candidate_pool']})")
    for row in section.get("pool_sweep", []):
        marker = " <- current" if row["pool"] == s["candidate_pool"] else ""
        print(
            f"    pool {row['pool']:>3}: hit {_fmt(row['hit_rate'])} / facts in context "
            f"{_fmt(row['context_fact_recall'])}{marker}"
        )
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


def build_registry(engine, work_dir: str, database: bool = True):
    """Agents as in production; database=False leaves out db_agent (a deployment without a database)."""
    from src.agent.multi_agent.registry import AgentRegistry
    from src.agent.multi_agent.sub_agents.compliance_agent import ComplianceAuditorAgent
    from src.agent.multi_agent.sub_agents.db_agent import DatabaseAgent
    from src.agent.multi_agent.sub_agents.doc_agent import DocumentRagAgent
    from src.agent.multi_agent.sub_agents.request_agent import ServiceRequestAgent
    from src.connectors.db_connector import DatabaseConnector
    from src.connectors.sample_db import create_sample_sqlite_db

    registry = AgentRegistry()
    registry.register(DocumentRagAgent(rag_engine=engine))
    if database:
        db_path = create_sample_sqlite_db(os.path.join(work_dir, "sample_enterprise.db"))
        connector = DatabaseConnector(database_url=f"sqlite:///{db_path}", allowed_tables=[])
        registry.register(DatabaseAgent(db_connector=connector))
    registry.register(ComplianceAuditorAgent(rag_engine=engine))
    # Requests are filed into the temporary work directory (REQUESTS_DB under DATA_DIR)
    registry.register(ServiceRequestAgent())
    return registry


def run_routing(chat_model, registry, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    from src.agent.multi_agent.supervisor import SupervisorAgent

    supervisor = SupervisorAgent(chat_model=chat_model, registry=registry)
    records = []
    progress = Progress("routing", len(cases))
    for case in cases:
        progress.begin(case["id"])
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
        print(f"  [{'ok' if ok else 'XX'}] {case['id']:<12} -> {predicted}  {progress.status()}")

    summary = {"accuracy": metrics.mean(float(r["correct"]) for r in records), "by_category": {}}
    for category in metrics.CATEGORIES:
        rows = [r for r in records if r["category"] == category]
        if rows:
            summary["by_category"][category] = metrics.mean(float(r["correct"]) for r in rows)
    return {"summary": summary, "cases": records}


def run_e2e(chat_model, registry, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    from langgraph.checkpoint.memory import MemorySaver

    from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
    from src.agent.grading import is_grade_passed
    from src.agent.language import detect_language, message_variants

    orchestrator = MultiAgentOrchestrator(chat_model=chat_model, registry=registry, checkpointer=MemorySaver())
    records = []
    progress = Progress("end-to-end", len(cases))
    for case in cases:
        progress.begin(case["id"])
        start = time.perf_counter()
        try:
            # Asked like a logged-in admin: documents unfiltered, requests allowed. No session, so requests are
            # filed without the confirmation turn.
            result = orchestrator.query(case["question"], user=EVAL_USER)
            error = None
        except Exception as e:  # keep evaluating the remaining cases
            result, error = {"answer": "", "sources": [], "active_agent": "error"}, f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - start

        answer = result.get("answer", "")
        returned_sources = {s.get("source") for s in result.get("sources", [])}
        system_refusals = message_variants("no_context") + message_variants("fallback")
        recall = metrics.fact_recall(answer, case["expected_facts"])
        # A refusal phrase inside an answer that has every expected fact is part of the answer ("hakları arasında
        # fark bulunmamaktadır"), not a refusal
        # The request hint added to "not found" answers is not part of the answer
        body = answer.strip()
        for hint in message_variants("request_hint_not_found"):
            body = body.removesuffix(hint).strip()
        refused = body in system_refusals or (metrics.is_refusal(answer) and recall != 1.0)
        # Did the system answer in the question's language? (None when either text gives no signal)
        question_language, answer_language = detect_language(case["question"]), detect_language(answer)
        language_match = question_language == answer_language if question_language and answer_language else None
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
            # Facts of the expected answer in the returned sources (chunk level) and evidence shown with the answer
            "context_fact_recall": metrics.fact_recall(
                "\n".join(src.get("content", "") for src in result.get("sources", [])), case["expected_facts"]
            ),
            "has_evidence": any(src.get("evidence") for src in result.get("sources", [])),
            "refused": refused,
            "language_match": language_match,
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
        print(
            f"  [{status}] {case['id']:<12} {latency:6.1f}s  agent={record['agent']}  facts={_fmt(recall)}  "
            f"{progress.status()}"
        )

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
        "context_fact_recall": metrics.mean(r["context_fact_recall"] for r in records),
        # Verified answers that show the sentence they rely on
        "evidence_rate": rate([r for r in records if r["grounded"]], "has_evidence"),
        "grounded_rate": rate(records, "grounded"),
        # Answerable questions the system refused (too strict) vs. unanswerable questions it answered (hallucination risk)
        "false_refusal_rate": rate(answerable, "refused"),
        "language_match_rate": rate(records, "language_match"),
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
    print(f"  expected facts in sources     : {_fmt(s['context_fact_recall'])}")
    print(f"  verified answers with evidence: {_fmt(s['evidence_rate'])}")
    print(f"  grounded (Self-RAG passed)    : {_fmt(s['grounded_rate'])}")
    print(f"  false refusals                : {_fmt(s['false_refusal_rate'])}")
    print(f"  out-of-scope refused          : {_fmt(s['out_of_scope_refusal_rate'])}")
    print(f"  answered in question language : {_fmt(s.get('language_match_rate'))}")
    for r in section["cases"]:
        if r.get("language_match") is False:
            print(f"    wrong language: {r['id']} ({r['agent']})")
    print(f"  latency p50 / p95             : {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    if s["errors"]:
        print(f"  ERRORS                        : {s['errors']}")


# ─────────────────────────────── Main ───────────────────────────────


def load_agents_dataset(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip() and not line.lstrip().startswith("#")]


def run_agents(chat_model, registry, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Plans (which agents a question needs), the combined answers' facts, and questions back.

    plan cases: the supervisor must plan exactly the expected agents (asked without a conversation, so it cannot
    ask back); with expected_facts the whole workflow answers and the facts are looked up in the answer.
    clarify / no_clarify cases: asked in a conversation (whole workflow), the assistant should (not) ask back.
    """
    from langgraph.checkpoint.memory import MemorySaver

    from src.agent.multi_agent.orchestrator_graph import MultiAgentOrchestrator
    from src.agent.multi_agent.supervisor import SupervisorAgent

    supervisor = SupervisorAgent(chat_model=chat_model, registry=registry)
    orchestrator = MultiAgentOrchestrator(chat_model=chat_model, registry=registry, checkpointer=MemorySaver())
    records = []
    progress = Progress("agents", len(cases))
    for case in cases:
        progress.begin(case["id"])
        record: Dict[str, Any] = {"id": case["id"], "kind": case["kind"]}
        start = time.perf_counter()
        if case["kind"] == "plan":
            decision = supervisor.route({"question": case["question"], "chat_history": [], "agent_trace": []})
            planned = [step["agent"] for step in decision.get("plan") or []]
            record.update(
                planned=planned,
                uses=[step.get("uses") for step in decision.get("plan") or []],
                correct=sorted(planned) == sorted(case["expected_agents"]),
            )
            if case.get("expected_facts"):
                result = orchestrator.query(case["question"], user=EVAL_USER)
                record.update(
                    answer=result.get("answer", ""),
                    agents=result.get("agents", []),
                    fact_recall=metrics.fact_recall(result.get("answer", ""), case["expected_facts"]),
                )
            mark = "ok" if record["correct"] else "XX"
            facts = _fmt(record.get("fact_recall"))
            print(f"  [{mark}] {case['id']:<14} -> {planned}  facts: {facts}  {progress.status()}")
        else:
            # In a conversation, through the whole workflow: doc_agent asks back after seeing the rules
            result = orchestrator.query(case["question"], thread_id=f"eval-{case['id']}", user=EVAL_USER)
            clarification = result.get("clarification")
            record.update(asked_back=bool(clarification), clarification=clarification)
            record["correct"] = record["asked_back"] == (case["kind"] == "clarify")
            mark = "ok" if record["correct"] else "XX"
            asked = f"asked back: {record['asked_back']}  {clarification or ''}"
            print(f"  [{mark}] {case['id']:<14} {asked}  {progress.status()}")
        record["latency_s"] = round(time.perf_counter() - start, 2)
        records.append(record)

    def share(kind_filter, key="correct"):
        rows = [r for r in records if kind_filter(r)]
        return metrics.mean(float(r[key]) for r in rows) if rows else None

    plans = [r for r in records if r["kind"] == "plan"]
    summary = {
        "plan_accuracy": share(lambda r: r["kind"] == "plan"),
        "composite_plan_accuracy": share(lambda r: r["kind"] == "plan" and r["id"].startswith("ag-plan")),
        "single_plan_accuracy": share(lambda r: r["kind"] == "plan" and r["id"].startswith("ag-single")),
        "fact_recall": metrics.mean(r["fact_recall"] for r in plans if r.get("fact_recall") is not None),
        "clarify_rate_ambiguous": share(lambda r: r["kind"] == "clarify", "asked_back"),
        "clarify_rate_clear": share(lambda r: r["kind"] == "no_clarify", "asked_back"),
    }
    return {"summary": summary, "cases": records}


def print_agents(section: Dict[str, Any]) -> None:
    s = section["summary"]
    print(f"  plans right                      : {_fmt(s['plan_accuracy'])}")
    print(f"    composite questions            : {_fmt(s['composite_plan_accuracy'])}")
    print(f"    single questions (not split)   : {_fmt(s['single_plan_accuracy'])}")
    print(f"  facts in the answers             : {_fmt(s['fact_recall'])}")
    print(f"  asked back on ambiguous questions: {_fmt(s['clarify_rate_ambiguous'])}")
    print(f"  asked back on clear questions    : {_fmt(s['clarify_rate_clear'])} (lower is better)")


def load_grader_dataset(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip() and not line.startswith("#")]


def run_grader(engine, chat_model, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Answer check on correct answers and wrong copies of them (see evals/build_grader_dataset.py).

    'grader_only' is the grader's first verdict (the check before this stage existed); 'full' adds the second
    opinion and the code checks, as doc_agent runs it before refining.
    """
    from src.agent.verification import check_answer

    records = []
    progress = Progress("answer check", len(items))
    for item in items:
        progress.begin(item["id"])
        start = time.perf_counter()
        result = engine.search(item["question"])
        check = check_answer(
            chat_model, result.get("context", ""), item["question"], item["answer"], result.get("sources", [])
        )
        records.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "grader_only": check.first_verdict,
                "full": check.passed,
                "grade": check.grade,
                "latency_s": round(time.perf_counter() - start, 2),
            }
        )
        print(
            f"  {item['id']:<24} grader {'pass' if check.first_verdict else 'FAIL'}  "
            f"full {'pass' if check.passed else 'FAIL'}  {progress.status()}"
        )

    def accepted(kind, mode):
        return metrics.mean(float(r[mode]) for r in records if r["kind"] == kind)

    kinds = sorted({r["kind"] for r in records})
    summary = {
        mode: {
            "correct_accepted": accepted("original", mode),
            **{
                f"wrong_rejected_{kind}": 1 - accepted(kind, mode)
                for kind in kinds
                if kind != "original" and accepted(kind, mode) is not None
            },
        }
        for mode in ("grader_only", "full")
    }
    summary["items"] = len(records)
    return {"summary": summary, "cases": records}


def print_grader(section: Dict[str, Any]) -> None:
    s = section["summary"]
    print("\n== Answer check ==")
    print(f"  items: {s['items']}                     grader only  full check")
    for metric in s["full"]:
        print(f"  {metric:<32}: {_fmt(s['grader_only'].get(metric)):>10}  {_fmt(s['full'][metric]):>10}")


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
    parser.add_argument(
        "--retrieval-pool",
        type=int,
        default=DEFAULT_RETRIEVAL_POOL,
        help="Candidates per question scored by the reranker in the retrieval stage.",
    )
    parser.add_argument("--no-index-cache", action="store_true", help="Always rebuild the index (no evals/.cache).")
    parser.add_argument(
        "--grader-dataset", default=DEFAULT_GRADER_DATASET, help="Answer-check dataset for the 'grader' stage."
    )
    parser.add_argument(
        "--agents-dataset", default=DEFAULT_AGENTS_DATASET, help="Collaboration dataset for the 'agents' stage."
    )
    parser.add_argument(
        "--no-database",
        action="store_true",
        help="Leave out db_agent and the demo database, like a deployment with SAMPLE_DB_ENABLED=false.",
    )
    args = parser.parse_args(argv)

    stages = STAGES if args.stages == "all" else tuple(s.strip() for s in args.stages.split(",") if s.strip())
    unknown = set(stages) - set(STAGES) - set(EXTRA_STAGES)
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
                "router_model": config.OLLAMA_ROUTER_MODEL or config.OLLAMA_MODEL,
                "grader_model": config.OLLAMA_GRADER_MODEL or config.OLLAMA_MODEL,
                "ollama_num_ctx": config.OLLAMA_NUM_CTX,
                "ollama_num_predict": config.OLLAMA_NUM_PREDICT,
                "rag_min_similarity": config.RAG_MIN_SIMILARITY,
                "rag_min_reranker_score": config.RAG_MIN_RERANKER_SCORE,
                "reranker_top_n": config.RERANKER_TOP_N,
                "chunk_size": config.CHUNK_SIZE,
                "chunk_overlap": config.CHUNK_OVERLAP,
                "article_chunk_size": config.ARTICLE_CHUNK_SIZE,
                "ollama_num_gpu": config.OLLAMA_NUM_GPU,
                "grader_mode": config.GRADER_MODE,
                "grader_second_opinion": config.GRADER_SECOND_OPINION,
                "grader_number_check": config.GRADER_NUMBER_CHECK,
                "grader_transitional_check": config.GRADER_TRANSITIONAL_CHECK,
                "grader_quantity_check": config.GRADER_QUANTITY_CHECK,
                "answer_evidence_first": config.ANSWER_EVIDENCE_FIRST,
                "doc_agent_tools": config.DOC_AGENT_TOOLS,
                "database": not args.no_database,
            },
            "summary": {},
            "details": {},
        }
        print(f"Evaluating {len(cases)} cases, stages: {', '.join(args.stages)}")

        if {"routing", "e2e", "grader", "agents"} & set(args.stages):
            from src.agent.llm import check_ollama

            # Fail fast instead of recording an error for every question
            llm_problem = check_ollama()
            if llm_problem:
                print(f"LLM not available: {llm_problem}")
                return 1
            print(f"LLM: {config.OLLAMA_MODEL} via Ollama at {config.OLLAMA_BASE_URL}")
            if config.OLLAMA_GRADER_MODEL and config.OLLAMA_GRADER_MODEL != config.OLLAMA_MODEL:
                print(f"Answers are checked by: {config.OLLAMA_GRADER_MODEL}")

        # Routing only needs the agents' descriptions, not the vector store
        engine = None
        if {"retrieval", "e2e", "grader", "agents"} & set(args.stages):
            print("Indexing corpus...")
            engine, chunk_count = build_engine(
                args.corpus, work_dir, cache_dir=None if args.no_index_cache else DEFAULT_INDEX_CACHE
            )
            report["config"]["corpus_chunks"] = chunk_count

        if "retrieval" in args.stages:
            print("\n== Running retrieval ==")
            section = run_retrieval(engine, cases, pool=args.retrieval_pool)
            report["summary"]["retrieval"] = section["summary"]
            report["details"]["retrieval"] = section
            print_retrieval(section)

        if "routing" in args.stages or "e2e" in args.stages:
            from src.agent.llm import create_chat_model

            chat_model = create_chat_model()
            registry = build_registry(engine, work_dir, database=not args.no_database)

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

        if "agents" in args.stages:
            from src.agent.llm import create_chat_model

            agent_cases = load_agents_dataset(args.agents_dataset)
            print(f"\n== Agent collaboration ({len(agent_cases)} cases) ==")
            section = run_agents(
                create_chat_model(), build_registry(engine, work_dir, database=not args.no_database), agent_cases
            )
            report["summary"]["agents"] = section["summary"]
            report["details"]["agents"] = section
            print_agents(section)

        if "grader" in args.stages:
            from src.agent.llm import create_chat_model

            items = load_grader_dataset(args.grader_dataset)
            print(f"\n== Checking {len(items)} answers ==")
            section = run_grader(engine, create_chat_model(), items)
            report["summary"]["grader"] = section["summary"]
            report["details"]["grader"] = section
            print_grader(section)

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
