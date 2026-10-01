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
| `agents` | Ollama | Run only when named (`--stages agents`, dataset `evals/dataset_agents.jsonl`, `--agents-dataset` for another): whether composite questions (documents + database) get one step per agent and single questions are not split, the expected facts in the combined answers, and how often the assistant asks back on ambiguous questions about the asker's own case (should) and on clear ones (should not). |

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
| `language_match_rate` | Answers written in the language of the question (detected with `src/agent/language.py`). Mismatches are listed as `wrong language` lines. |
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
| `category` | ✅ | `document`, `compliance`, `database`, `request`, `greeting`, or `out_of_scope`. |
| `question` | ✅ | The user question. |
| `expected_agent` | ✅ | Agent name or list of acceptable agents; `supervisor` means a direct answer. |
| `expected_sources` | | Corpus file names that contain the answer. Required for `document` and `compliance`. |
| `expected_facts` | | Strings that must appear in the answer. A list inside the list gives alternatives: `[["Salı", "Tuesday"], "10:00"]`. |
| `expect_refusal` | | The system should say it does not know. Defaults to `true` for `out_of_scope`. |

The bundled set has 51 questions over six fictional NovaTech policy documents (`evals/corpus/`) and the sample database. The documents deliberately overlap (several numbers, approval rules, and "30 days" appear in more than one document), so retrieval has to pick the right one.

### University dataset (laws and regulations)

`evals/dataset_university.jsonl` has 127 questions over three documents in `evals/corpus_university/`: the Turkish Higher Education Law No. 2547 (about 420,000 characters), the Open Higher Education Regulation, and Atatürk University's associate and undergraduate regulation (830 chunks with article-aware chunking). 105 document questions (among them `-inf-` questions that need a small inference, e.g. whether 75% attendance meets an 80% requirement, questions that span two documents, and English questions), 9 compliance scenarios, 2 service requests, 1 greeting, and 10 questions the documents do not answer.

```bash
RAG_MIN_RERANKER_SCORE=0.05 python -m evals.run_eval --dataset evals/dataset_university.jsonl --corpus evals/corpus_university --no-database
```

`--no-database` leaves out `db_agent` and the demo sales database, as in a university deployment with `SAMPLE_DB_ENABLED=false`. The index is cached in `evals/.cache/` (building it takes about 8 minutes on the CPU); the retrieval stage scores 50 candidates per question and takes about 30 minutes on the CPU, routing and end-to-end about 30 minutes.

### Using your own documents

The bundled set measures the system, not your data. To tune for your documents:

1. Copy 20–50 real questions your users ask into a new JSONL file, with the file that answers each one.
2. Add 5–10 questions your documents do **not** answer; these drive the threshold recommendation.
3. Run `python -m evals.run_eval --corpus path/to/your/docs --dataset path/to/your_questions.jsonl`.

Keep private datasets and documents out of the repository.

---

## 📊 Current Results

Default settings, bundled dataset (51 questions), `qwen2.5:7b` via Ollama on an RTX 3060 Laptop GPU (6 GB; Ollama kept 82% of the model on the GPU and 18% on the CPU), embedding and reranker on CPU. A full `--stages all` run takes about 15 minutes on this machine. A re-run with the changes for laws and regulations (article-aware chunking only applies to documents with article headings, quote grader, 4 chunks) gave the same answer accuracy (95.1%) with 6.8–7.0 s / 16.5 s latency.

| Metric | Value |
| :--- | :---: |
| Retrieval hit rate / MRR | 100% / 1.00 |
| Off-topic questions that retrieve no context | 100% |
| Routing accuracy | 98% |
| Answer accuracy | 95% |
| ↳ documents / compliance / database | 100% / 100% / 80% |
| Grounded answers (Self-RAG passed) | 100% |
| Off-topic questions refused | 100% |
| Answerable questions refused | 2% |
| Answers in the question's language | 100% |
| Latency p50 / p95 | 7.3 s / 23.2 s |

On the 13 held-out questions (see below): routing 12/13 and 9/10 correct answers.

Remaining failures:
* `db-04` filters on `durum = 'çözüldü'`, but the column stores `'Resolved'`. The SQL prompt shows column names, not the values stored in them.
* `db-10` (a support ticket code) is routed to `doc_agent`, which correctly answers that the information is not in the documents instead of guessing.

### Agent collaboration (`--stages agents`)

Same machine and model, default corpus and sample database, 18 questions: 4 composite (a rule and a database value), 3 single, 3 ambiguous questions about the asker's case, 8 clear ones. "Before" is the first run after adding questions back and steps that build on each other, with the supervisor alone deciding both.

| Metric | Before | Now |
| :--- | :---: | :---: |
| Composite questions planned with both agents | 25% | 100% |
| Single questions not split | 100% | 100% |
| Expected facts in the answers | 78.6% | 100% |
| Asked back on ambiguous questions | 0% | 100% |
| Asked back on clear questions (lower is better) | 0% | 0% |
| Routing accuracy on the main dataset (51 questions) | 96.1% ¹ | 100% |

¹ The request agent's new actions (cancel, add a note) pulled "SR-2026-103 numaralı destek talebi" (a database record) to the request agent; the routing rules now name requests "filed with this assistant (numbered like #12)" and give an example of a coded database record.

* **Composite questions:** the 7B supervisor sent "Monitör talebi en fazla kaç adet ve NovaView monitörün birim fiyatı nedir?" only to `db_agent`. Telling it to list the things the question asks first, with two examples of a rule plus a database value, planned all four with both agents; with the reminder that a verdict on one's own action belongs to `compliance_agent`, routing on the main dataset stayed at 100%.
* **Questions back** moved from the supervisor to `doc_agent`: the supervisor does not see the rules, so it cannot know that leave depends on seniority. `doc_agent` asks only for short questions about the asker's own case, in a conversation; the model only describes the passage (`depends_on`, `stated`, the question, short options) and the code decides. A single yes/no from the model said "no" every time; reading only the best-matching passage stopped it from asking about seniority for a remote-work question.
* The questions read "Kıdeminiz kaç yıl?" (1-5 / 5-15 / 15+ years) and "Yurt içinde mi yurt dışında mı seyahat ediyorsunuz?". Steps with `uses` (a step that looks up what an earlier one found) are covered by unit tests; the four composite questions have independent parts, so the model planned none.

### University dataset

Same machine, with the whole model on the GPU (`OLLAMA_NUM_GPU=99`), `RAG_MIN_RERANKER_SCORE=0.05`, and `--no-database`. The e2e evaluation asks as a logged-in admin without a session (documents unfiltered, requests filed without the confirmation turn). The baseline ran the code before this round of changes on the same 127 questions, and both reports are scored with the same rules.

| Metric | Before | Article-aware chunking, quote grader, 4 chunks |
| :--- | :---: | :---: |
| Retrieval hit rate / MRR | 99.1% / 0.97 | 100% / 1.00 |
| Routing accuracy | 95.3% | 99.2% |
| Answer accuracy | 78.4% | 90.5% |
| ↳ documents / compliance / requests | 76.2% / 100% / 100% | 91.4% / 77.8% / 100% |
| Answerable questions refused | 19 of 116 | 9 of 116 |
| Off-topic questions refused | 9 of 10 | 9 of 10 |
| Answers in the question's language | 100% | 100% |
| Latency p50 / p95 | 9.6 s / 22.2 s ¹ | 11.9 s / 22.2 s |

¹ The baseline ran with 18% of the model on the CPU and without the quote grader, so its latency is not directly comparable.

Most errors of the baseline were not wrong answers but correct answers the yes/no grader rejected (19 false refusals), while retrieval already found the right document for 99% of the questions. Measured step by step (document accuracy):

| Step | Documents | Refused |
| :--- | :---: | :---: |
| Baseline | 76.2% | 19 |
| Article-aware chunking + quote grader | 79.0% | 14 |
| Verdict first in the grader's JSON, `RAG_MIN_RERANKER_SCORE=0.05` | 81.0% | 13 |
| Digits for numbers in words, cross-references, grader objection check, JSON retry | 88.6% | 7 |
| 4 chunks, transitional articles last in the context | 90.5% | 10 |
| + the grader's objection passed to the refinement step | 91.4% | 9 |

Runs of the same configuration differ by a few questions (the grader's decisions are not fully stable), so single-question changes between steps are noise; the trend is not. With three chunks instead of four, the last configuration reached 87.6%.

* **Numbers in words** fixed the associate-professor language exam question (the article in force says "elli beş puan", a transitional article "65" in digits) and the Quality Council's member count ("on üç").
* **Transitional articles last** fixed the retirement age in Turkish and English (67 instead of the transitional 70/69/68).
* **Threshold:** with article-aware chunks the lowest reranker score of an answerable question is 0.12 (an English question) and the highest off-topic score 0.057; 0.05 rejects 9 of 10 off-topic questions before the LLM. On the demo company documents (plain chunks) 0.05 would drop 6.5% of the answerable questions, so the default stays at 0.005.
* **Still wrong:** the penalty for cheating (the model mixes it up with attempted cheating, which is listed in the neighbouring piece of the same article), two sentences with two rules each ("beş yıl … on yıl", "katkı payı … öğrenim ücreti"), and a compliance scenario on party membership, which the law allows, reported as a violation. Answers that compute a number (a year, a sum) are often refused, because the computed number is not in the documents.

On the demo dataset, four chunks instead of three changed no answer (95.1% either way, documents 100%) and added 0.2 s median latency.

---

## 📈 How We Got Here

The same 51 questions were measured after each step. The 13 questions `db-06`–`db-10`, `cmp-06`–`cmp-08`, `oos-06`–`oos-08`, `doc-hr-05`, and `doc-kvkk-03` were added before step 1 and never used to choose prompt wording, so they show whether a change generalizes beyond the questions used for tuning.

| Metric | Baseline (1.5B) | Step 1: gate + routing (1.5B) | Step 2: `qwen2.5:7b` via Ollama |
| :--- | :---: | :---: | :---: |
| Off-topic questions that retrieve no context | 0% | 100% | 100% |
| Routing accuracy | 67% | 82% | 98% |
| ↳ documents / compliance / database | 91% / 38% / 0% | 83% / 88% / 70% | 100% / 100% / 90% |
| Answer accuracy | 59% | 73% | 95% |
| ↳ documents / compliance / database | 96% / 25% / 0% | 91% / 63% / 40% | 100% / 100% / 80% |
| Off-topic questions refused | 50% | 100% | 100% |
| Answerable questions refused | 17% | 7% | 2% |
| Held-out routing / correct answers | 5/13 / 2/10 | 9/13 / 6/10 | 12/13 / 9/10 |

Latency is not compared across all three columns because other work ran on the machine during the baseline measurement. Between step 1 and step 2 it improved from 10.2 s / 39.2 s (p50 / p95) to 7.3 s / 23.2 s.

### Step 1: relevance gate and routing (still on the 1.5B model)
1. **Relevance gate (`RAG_MIN_RERANKER_SCORE=0.005`).** Bi-encoder similarity could not separate off-topic questions from answerable ones: off-topic questions reached 0.59 while one answerable question scored only 0.48. The cross-encoder score separates them: the highest off-topic score is 0.0036 and the lowest answerable score is 0.0065. The margin is narrow, so re-run the sweep on your own documents before relying on the default. With no context left, `doc_agent` says the information is not in the documents and `compliance_agent` returns `[UNDETERMINED]`, both without calling the LLM. 0.01 would have been too strict: it drops one of the held-out questions.
2. **Database routing.** `db_agent` tells the supervisor which tables and columns exist (`get_routing_context()`). Before that, the model could not know that stock or prices live in the database.
3. **Agent descriptions.** Routing depends more on the agents' descriptions than on the supervisor rules. The old `compliance_agent` description ("policies, privacy regulations, HR rules") pulled plain policy questions away from `doc_agent`, and the table list alone made this worse. Narrow descriptions fixed both: rewriting only the rules left routing at 66%, while rewriting the descriptions raised it to 87% on the tuning questions.

After step 1 the remaining errors were limits of the 1.5B model: invented SQL columns, misread numbers (170,000 TL reported as 17,000 TL), policy questions phrased with "can"/"must" (`-ebilir`, `-meli`) routed to `compliance_agent`, and a wrong answer the Self-RAG grader accepted (26 instead of 20 leave days).

### Step 2: switching the LLM to `qwen2.5:7b` via Ollama
Same code and dataset; only the LLM changed. The 7B model fixed every step-1 error listed above except the database value mismatch (`db-04`). This result is why the in-process HuggingFace backend was removed and the LLM now always runs on Ollama.

### Step 3: answering in the question's language
The `language_match_rate` metric showed that only 32 of 51 Turkish questions (63%) got a Turkish answer: fixed texts such as "not found in company documents" and the greeting were hard-coded in English, and `db_agent` and `compliance_agent` switched to English when the table data or the report template was English. Follow-up questions made it worse. After localizing the fixed texts, naming the target language in every prompt, and localizing the compliance report headings, all 51 answers match the question's language; accuracy, routing, and refusal rates did not change.

---

## 🗄️ Database Integration Tests

The read-only guarantees for PostgreSQL and MySQL are tested against real servers in `tests/data/test_db_integration.py`. The tests bypass the SQL guard on purpose and check that the database itself rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, and data-modifying CTEs, and that the statement timeout stops long queries. CI runs them against PostgreSQL 16 and MySQL 8.4 service containers. Locally they are skipped unless you point them at a server:

```bash
TEST_POSTGRES_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/olra_test \
TEST_MYSQL_URL=mysql+pymysql://root:root@localhost:3306/olra_test \
pytest tests/data/test_db_integration.py -v
```

Use a disposable database: the tests create and drop a table named `it_items`.
