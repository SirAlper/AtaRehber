# 📏 Evaluation Guide

Changes to retrieval, chunking, prompts, routing, or agents can make answers better or worse in ways unit tests do not show. The evaluation harness in `evals/` answers the question *"did this change help?"* with numbers, using a labeled question set and the real models.

---

## 🚀 Quick Start

Run from the repository root with the project's virtual environment:

```bash
# Retrieval only: embedding + reranker, no LLM (about 3 minutes on CPU)
python -m evals.run_eval

# Retrieval + supervisor routing + end-to-end answers (needs Ollama with OLLAMA_MODEL pulled)
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
| `routing` | Ollama | Whether the supervisor picks the expected agent. |
| `e2e` | Ollama | The full workflow (`MultiAgentOrchestrator.query`): answer correctness, refusals, Self-RAG grounding, latency. |

### Retrieval metrics

| Metric | Meaning |
| :--- | :--- |
| `hit_rate` | Share of answerable questions where a chunk from an expected source is among the chunks passed to the LLM (`RERANKER_TOP_N`). |
| `mrr` | Mean reciprocal rank of the first relevant chunk (1.0 = always first). |
| `hit_rate_without_threshold` | Hit rate if `RAG_MIN_SIMILARITY` were disabled. A gap to `hit_rate` means the threshold drops relevant chunks. |
| `out_of_scope_rejection` | Share of off-topic questions for which no chunk passes the thresholds, so `doc_agent` answers "not found" without calling the LLM. |
| `recommended_min_similarity` | From the threshold sweep: the value that keeps the best recall and rejects the most off-topic questions. |
| `recommended_min_reranker_score` | The same analysis for the cross-encoder score (`RAG_MIN_RERANKER_SCORE`). |

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
RAG_MIN_RERANKER_SCORE=0.01 python -m evals.run_eval
RERANKER_TOP_N=5 CHUNK_SIZE=400 python -m evals.run_eval --stages all
OLLAMA_MODEL=qwen2.5:3b python -m evals.run_eval --stages all     # pull it first: ollama pull qwen2.5:3b
```

This `VAR=value command` form works in bash. In PowerShell, set the variable first and remove it afterwards:
```powershell
$env:OLLAMA_MODEL = "qwen2.5:3b"
python -m evals.run_eval --stages all
Remove-Item Env:OLLAMA_MODEL
```

The routing and end-to-end stages need a running Ollama server with `OLLAMA_MODEL` pulled; the harness checks this first and stops with the fix if not. Each report records the model under `config.llm_model`.

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

The bundled set has 51 questions over six fictional NovaTech policy documents (`evals/corpus/`) and the sample database. The documents deliberately overlap (several numbers, approval rules, and "30 days" appear in more than one document), so retrieval has to pick the right one.

### Using your own documents

The bundled set measures the system, not your data. To tune for your documents:

1. Copy 20–50 real questions your users ask into a new JSONL file, with the file that answers each one.
2. Add 5–10 questions your documents do **not** answer; these drive the threshold recommendation.
3. Run `python -m evals.run_eval --corpus path/to/your/docs --dataset path/to/your_questions.jsonl`.

Keep private datasets and documents out of the repository.

---

## 📊 Results

Default settings, bundled dataset (51 questions), `qwen2.5-1.5b` (HuggingFace backend) on an RTX 3060 Laptop GPU, embedding and reranker on CPU. "Before" is the code before the reranker gate and the routing changes.

| Metric | Before | After |
| :--- | :---: | :---: |
| Retrieval hit rate / MRR | 100% / 1.00 | 100% / 1.00 |
| Off-topic questions that retrieve no context | 0% | **100%** |
| Routing accuracy | 67% | **82%** |
| ↳ documents / compliance / database | 91% / 38% / **0%** | 83% / 88% / **70%** |
| Answer accuracy | 59% | **73%** |
| ↳ documents / compliance / database | 96% / 25% / 0% | 91% / 63% / 40% |
| Off-topic questions refused | 50% | **100%** |
| Answerable questions refused | 17% | 7% |

The 13 questions added before tuning (`db-06`–`db-10`, `cmp-06`–`cmp-08`, `oos-06`–`oos-08`, `doc-hr-05`, `doc-kvkk-03`) were not used to choose the prompt wording. On them, routing went from 5/13 to 9/13 and correct answers from 2/10 to 6/10, so the gains are not limited to the questions used during tuning.

What changed and why:
1. **Relevance gate (`RAG_MIN_RERANKER_SCORE=0.005`).** Bi-encoder similarity could not separate off-topic questions from answerable ones: off-topic questions reached 0.59 while one answerable question scored only 0.48. The cross-encoder score separates them: the highest off-topic score is 0.0036 and the lowest answerable score is 0.0065. The margin is narrow, so re-run the sweep on your own documents before relying on the default. With no context left, `doc_agent` says the information is not in the documents and `compliance_agent` returns `[UNDETERMINED]`, both without calling the LLM. 0.01 would have been too strict: it drops one of the held-out questions.
2. **Database routing.** `db_agent` now tells the supervisor which tables and columns exist (`get_routing_context()`). Before that, the 1.5B model could not know that stock or prices live in the database.
3. **Agent descriptions.** Routing depends more on the agents' descriptions than on the supervisor rules. The old `compliance_agent` description ("policies, privacy regulations, HR rules") pulled plain policy questions away from `doc_agent`, and the table list alone made this worse. Narrow descriptions fixed both: rewriting only the rules left routing at 66%, while rewriting the descriptions raised it to 87% on the tuning questions.

Remaining weaknesses, all limits of the 1.5B model rather than of retrieval or routing:
* `db_agent` reaches the right agent in 70% of cases but answers only 40% correctly. The generated SQL sometimes uses non-existent columns, and summaries misstate numbers (170,000 TL reported as 17,000 TL).
* A few policy questions phrased with "can"/"must" (`-ebilir`, `-meli`) still go to `compliance_agent`, and "Bu sistem neler yapabilir?" goes to `doc_agent` instead of a direct answer.
* The Self-RAG grader still passes one wrong answer (26 instead of 20 leave days).

### Switching the LLM to `qwen2.5:7b` (Ollama)

Same code and dataset, only the LLM changed: `qwen2.5-1.5b` in-process versus `qwen2.5:7b` served by Ollama. On the 6 GB RTX 3060 Laptop GPU, Ollama kept 82% of the 7B model on the GPU and 18% on the CPU.

| Metric | 1.5B (in-process) | 7B (Ollama) |
| :--- | :---: | :---: |
| Routing accuracy | 82% | **98%** |
| Answer accuracy | 73% | **95%** |
| ↳ documents / compliance / database | 91% / 63% / 40% | **100% / 100% / 80%** |
| Off-topic questions refused | 100% | 100% |
| Answerable questions refused | 7% | 2% |
| Latency p50 / p95 | 10.2 s / 39.2 s | **7.3 s / 23.2 s** |

On the held-out questions: routing 12/13 and 9/10 correct answers. The larger model also fixed the reasoning error the Self-RAG grader had missed (20 leave days instead of 26). This result is why the in-process HuggingFace backend was removed and the LLM now always runs on Ollama.

Remaining failures:
* `db-04` filters on `durum = 'çözüldü'`, but the column stores `'Resolved'`. The SQL prompt shows column names, not the values stored in them.
* `db-10` (a support ticket code) is routed to `doc_agent`, which correctly answers that the information is not in the documents instead of guessing.

---

## 🗄️ Database Integration Tests

The read-only guarantees for PostgreSQL and MySQL are tested against real servers in `tests/test_db_integration.py`. The tests bypass the SQL guard on purpose and check that the database itself rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, and data-modifying CTEs, and that the statement timeout stops long queries. CI runs them against PostgreSQL 16 and MySQL 8.4 service containers. Locally they are skipped unless you point them at a server:

```bash
TEST_POSTGRES_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/olra_test \
TEST_MYSQL_URL=mysql+pymysql://root:root@localhost:3306/olra_test \
pytest tests/test_db_integration.py -v
```

Use a disposable database: the tests create and drop a table named `it_items`.
