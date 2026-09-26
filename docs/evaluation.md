# 📏 Evaluation Guide

Changes to retrieval, chunking, prompts, routing, or agents can make answers better or worse in ways unit tests do not show. The evaluation harness in `evals/` answers the question *"did this change help?"* with numbers, using a labeled question set and the real models.

---

## 🚀 Quick Start

Run from the repository root with the project's virtual environment:

```bash
# Retrieval only: embedding + reranker, no LLM (about 3 minutes on CPU)
python -m evals.run_eval

# Retrieval + supervisor routing + end-to-end answers (loads the LLM)
python -m evals.run_eval --stages all

# Only some questions
python -m evals.run_eval --stages all --category database --ids db-01,db-02
```

The harness runs in a temporary directory. It indexes `evals/corpus/` into its own vector store and creates a fresh sample database, so your `data/` and `vector_db/` folders are never read or modified. Each run writes a JSON report to `evals/results/` (git-ignored).

---

## 🧪 Stages

| Stage | Needs | What it measures |
| :--- | :--- | :--- |
| `retrieval` | Embedding + reranker | Whether the right document reaches the LLM, and whether off-topic questions retrieve nothing. |
| `routing` | LLM | Whether the supervisor picks the expected agent. |
| `e2e` | LLM | The full workflow (`MultiAgentOrchestrator.query`): answer correctness, refusals, Self-RAG grounding, latency. |

### Retrieval metrics

| Metric | Meaning |
| :--- | :--- |
| `hit_rate` | Share of answerable questions where a chunk from an expected source is among the chunks passed to the LLM (`RERANKER_TOP_N`). |
| `mrr` | Mean reciprocal rank of the first relevant chunk (1.0 = always first). |
| `hit_rate_without_threshold` | Hit rate if `RAG_MIN_SIMILARITY` were disabled. A gap to `hit_rate` means the threshold drops relevant chunks. |
| `out_of_scope_rejection` | Share of off-topic questions for which no chunk passes the threshold, so `doc_agent` answers "not found" without calling the LLM. |
| `recommended_min_similarity` | From the threshold sweep: the value that keeps the best recall and rejects the most off-topic questions. |
| `recommended_min_reranker_score` | The same analysis for the cross-encoder score (informational; there is no such setting yet). |

Retrieval scores every chunk once, then replays the production selection (top 10 by similarity → threshold → rerank → top N). The sweeps therefore cost no extra model calls. The `MISS` and `LEAK` lines list the questions that failed and why.

### End-to-end metrics

| Metric | Meaning |
| :--- | :--- |
| `agent_accuracy` | The agent that answered matches the expected agent. |
| `answer_accuracy` | All expected facts appear in the answer (answerable questions only). |
| `fact_recall` | Share of expected facts found, averaged. |
| `source_hit_rate` | The answer cites an expected source. |
| `grounded_rate` | `doc_agent` answers that passed the Self-RAG grader. |
| `false_refusal_rate` | Answerable questions the system refused. Too high means it is too strict. |
| `out_of_scope_refusal_rate` | Unanswerable questions the system refused. Too low means hallucination risk. |
| `latency_p50_s` / `latency_p95_s` | Seconds per question. |

Facts are checked deterministically instead of with an LLM judge: small local models are unreliable judges, and a keyword check gives the same result on every run. Matching is case-insensitive (Turkish-aware), ignores thousands separators (`15.000` = `15000`), and numbers only match whole numbers (`2` does not match `2026`).

---

## 🔁 Comparing Changes

Run once before your change and once after, passing the first report:

```bash
python -m evals.run_eval --stages all                                        # on master
python -m evals.run_eval --stages all --compare evals/results/report_<before>.json
```

Only changed metrics are printed, for example `retrieval.out_of_scope_rejection  0.000 -> 0.600 (+0.600)`.

Settings are read from the environment, like the application itself, so you can compare configurations without editing code:

```bash
RAG_MIN_SIMILARITY=0.5 python -m evals.run_eval
RERANKER_TOP_N=5 CHUNK_SIZE=400 python -m evals.run_eval --stages all
LLM_BACKEND=ollama OLLAMA_MODEL=qwen2.5:7b python -m evals.run_eval --stages e2e
```

LLM output varies slightly between runs, so treat differences of one or two questions as noise.

---

## 📝 The Dataset

`evals/dataset.jsonl` holds one question per line:

```json
{"id": "doc-hw-04", "category": "document", "question": "Mühendislere yıllık ne kadar eğitim ve kitap bütçesi veriliyor?", "expected_agent": "doc_agent", "expected_sources": ["hardware_procurement.txt"], "expected_facts": ["15000"]}
```

| Field | Required | Description |
| :--- | :---: | :--- |
| `id` | ✅ | Unique identifier. |
| `category` | ✅ | `document`, `compliance`, `database`, `greeting`, or `out_of_scope`. |
| `question` | ✅ | The user question. |
| `expected_agent` | ✅ | Agent name or list of acceptable agents; `supervisor` means a direct answer. |
| `expected_sources` | | Corpus file names that contain the answer. Required for `document` and `compliance`. |
| `expected_facts` | | Strings that must appear in the answer. A list inside the list gives alternatives: `[["Salı", "Tuesday"], "10:00"]`. |
| `expect_refusal` | | The system should say it does not know. Defaults to `true` for `out_of_scope`. |

The bundled set has 38 questions over six fictional NovaTech policy documents (`evals/corpus/`) and the sample database. The documents deliberately overlap (several numbers, approval rules, and "30 days" appear in more than one document), so retrieval has to pick the right one.

### Using your own documents

The bundled set measures the system, not your data. To tune for your documents:

1. Copy 20–50 real questions your users ask into a new JSONL file, with the file that answers each one.
2. Add 5–10 questions your documents do **not** answer; these drive the threshold recommendation.
3. Run `python -m evals.run_eval --corpus path/to/your/docs --dataset path/to/your_questions.jsonl`.

Keep private datasets and documents out of the repository.

---

## 📊 Baseline

Default settings, bundled dataset, `qwen2.5-1.5b` (HuggingFace backend) on an RTX 3060 Laptop GPU, embedding and reranker on CPU:

| Metric | Value | Notes |
| :--- | :---: | :--- |
| Retrieval hit rate / MRR | 100% / 1.00 | The six-document corpus is small; your own documents will be harder. |
| Off-topic rejection at `RAG_MIN_SIMILARITY=0.325` | 0% | Every off-topic question retrieves chunks. |
| Suggested `RAG_MIN_SIMILARITY` | 0.50 | 60% rejection, but relevant chunks start dropping at 0.525: thin margin. |
| Suggested reranker score threshold | 0.01 | 100% rejection with no recall loss: a much clearer separation. |
| Routing accuracy | 76% | Documents 95%, compliance 40%, **database 0%**. |
| Answer accuracy | 71% | Documents 95%, compliance 40%, database 0%. |
| Off-topic questions refused | 60% | `compliance_agent` issued verdicts on off-topic questions. |
| Latency p50 / p95 | 7.8 s / 26.3 s | Compliance reports are the slowest. |

What this baseline shows:
1. **Database questions never reach `db_agent`.** The supervisor only sees generic agent descriptions. The 1.5B model does not know that stock or prices live in the database, so it routes them to `doc_agent`.
2. **The similarity threshold does not reject off-topic questions**, while the reranker score separates them cleanly.
3. **`compliance_agent` has no grounding check.** With irrelevant context it still returns a verdict (for example `[COMPLIANT]` for a parking question).
4. The Self-RAG grader passed at least one wrong answer (26 instead of 20 leave days), so grading does not catch reasoning errors over correct context.

---

## 🗄️ Database Integration Tests

The read-only guarantees for PostgreSQL and MySQL are tested against real servers in `tests/test_db_integration.py`. The tests bypass the SQL guard on purpose and check that the database itself rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, and data-modifying CTEs, and that the statement timeout stops long queries. CI runs them against PostgreSQL 16 and MySQL 8.4 service containers. Locally they are skipped unless you point them at a server:

```bash
TEST_POSTGRES_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/olra_test \
TEST_MYSQL_URL=mysql+pymysql://root:root@localhost:3306/olra_test \
pytest tests/test_db_integration.py -v
```

Use a disposable database: the tests create and drop a table named `it_items`.
