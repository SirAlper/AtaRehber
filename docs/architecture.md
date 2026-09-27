# 🏗️ System Architecture & Engineering Principles

`OpenLocalRagAgents` is built upon **Two-Stage Retrieval**, a **LangGraph Multi-Agent Supervisor workflow**, **Role-Based Access Control (RBAC)**, and **Hash-Chained Audit Logging**, designed to execute 100% locally on private enterprise hardware without sending proprietary data to third-party cloud APIs.

---

## 📐 High-Level Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            Enterprise Client Layer                               │
│       Streamlit Enterprise UI (Port 8501)   │   External Workplace Apps / Bots   │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ HTTP REST (Bearer JWT)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             FastAPI Gateway (Port 8000)                          │
│  ┌─────────────────────────┐  ┌────────────────────────┐  ┌───────────────────┐  │
│  │  CORS & Rate Limiting   │  │ JWT & RBAC Dependencies│  │ Structured Logger │  │
│  │  (per account / per IP) │  │ (admin/editor/viewer)  │  │ (src.core.logger) │  │
│  └─────────────────────────┘  └────────────────────────┘  └───────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                    Query Concurrency Manager (State)                       │  │
│  │      Ollama requests capped by asyncio.Semaphore(OLLAMA_NUM_PARALLEL)      │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────┬──────────────────────────────────┬───────────────────────┘
                        │                                  │
      Workflow Dispatch │                Audit & ETL Event │
                        ▼                                  ▼
┌────────────────────────────────────────────────────────┐  ┌──────────────────────────────────────┐
│  LangGraph Multi-Agent Workflow                        │  │  Data & Governance Layer             │
│                                                        │  │  ┌────────────────────────────────┐  │
│               ┌───────────────────────┐                │  │  │ Audit Logger (data/audit.db)   │  │
│               │ 👑 supervisor         │                │  │  │ SHA-256 hash-chained entries   │  │
│               │ intent routing,       │                │  │  └────────────────────────────────┘  │
│               │ forced_agent,         │                │  │  ┌────────────────────────────────┐  │
│               │ greeting fast path    │                │  │  │ Checkpointer                   │  │
│               └──┬────────┬────────┬──┘                │  │  │ multi_agent_conversations.db   │  │
│        ┌─────────┘        │        └──────────┐        │  │  └────────────────────────────────┘  │
│        ▼                  ▼                   ▼        │  │  ┌────────────────────────────────┐  │
│ ┌────────────┐   ┌─────────────┐   ┌──────────────────┐│  │  │ User Store (data/users.json)   │  │
│ │ doc_agent  │   │  db_agent   │   │ compliance_agent ││  │  │ bcrypt hashes, token versions  │  │
│ │ (Self-RAG) │   │(Text-to-SQL)│   │ (policy audit)   ││  │  └────────────────────────────────┘  │
│ └─────┬──────┘   └──────┬──────┘   └────────┬─────────┘│  │  ┌────────────────────────────────┐  │
│       └─────────────────┼───────────────────┘          │  │  │ Universal DB Connector         │  │
│                         ▼   direct answer ◄─ supervisor│  │  │ Postgres/MSSQL/MySQL/Oracle/   │  │
│                 ┌───────────────┐                      │  │  │ SQLite, read-only sessions     │  │
│                 │  record_turn  │──> [END]             │  │  └────────────────────────────────┘  │
│                 │(chat_history) │                      │  │                                      │
│                 └───────────────┘                      │  │                                      │
└──────────────────────┬─────────────────────────────────┘  └──────────────────────────────────────┘
                       │
       Context Scoring │ Generation Call
                       ▼
┌────────────────────────────────────────┐  ┌──────────────────────────────────────┐
│         Knowledge Retrieval Layer      │  │        LLM Serving (Ollama)          │
│                                        │  │                                      │
│  ┌──────────────────────────────────┐  │  │  Separate Ollama server process      │
│  │ ChromaDB Vector Store            │  │  │  - LangChain ChatOllama client       │
│  │ - BAAI/bge-m3 Dense Vectors      │  │  │  - Default model: qwen2.5:7b         │
│  │ - Contextual Chunking Headers    │  │  │                                      │
│  └──────────────────────────────────┘  │  │  - Explicit context window (num_ctx) │
│  ┌──────────────────────────────────┐  │  │  - Startup check: server reachable,  │
│  │ Cross-Encoder Reranker           │  │  │    model pulled                      │
│  │ - BAAI/bge-reranker-v2-m3        │  │  │  - No LLM weights in the API process │
│  └──────────────────────────────────┘  │  └──────────────────────────────────────┘
└────────────────────────────────────────┘
```

A single Ollama chat model client is created once (`get_chat_model()` in `src/api/state.py`) and shared by the supervisor and every sub-agent; the model itself runs in the Ollama server.

---

## 🔍 Two-Stage Retrieval & Cross-Encoder Reranking

Traditional naive RAG implementations rely solely on vector similarity, which frequently retrieves semantically adjacent but factually unhelpful text passages. Our architecture addresses this with a two-stage pipeline (`src/rag/rag_engine.py`):

### Stage 1: Fast Bi-Encoder Vector Search (`BAAI/bge-m3`)
* **Model:** `BAAI/bge-m3` (1024-dimensional, L2-normalized dense vectors).
* **Operation:** The query is vectorized and matched against ChromaDB to retrieve a broad candidate pool (`n_results=10`).
* **Similarity Thresholding:** Candidates below `RAG_MIN_SIMILARITY` (cosine similarity, default `0.325`) are discarded. This is only a coarse pre-filter: bi-encoder similarity cannot separate off-topic questions from answerable ones (see [Evaluation](evaluation.md)). New collections use cosine distance; collections created by older versions keep their L2 metric, and distances are converted so the same threshold applies to both.

### Stage 2: Full-Attention Cross-Encoder Reranking (`BAAI/bge-reranker-v2-m3`)
* **Model:** `BAAI/bge-reranker-v2-m3`.
* **Operation:** Remaining candidates are paired with the query (`[Query, Document Chunk]`) and scored jointly by the cross-encoder.
* **Relevance Gate:** Passages scoring below `RAG_MIN_RERANKER_SCORE` (0–1, default `0.005`) are dropped. If none remain, the question gets no context, so `doc_agent` answers "not found in company documents" and `compliance_agent` returns an `[UNDETERMINED]` verdict without calling the LLM. On the evaluation set this rejects all off-topic questions while keeping every answerable one.
* **Output:** The top `RERANKER_TOP_N` (default `3`) passages are concatenated into the LLM context.

Index writes are serialized with a write lock (also used by backups), and per-document chunk statistics are cached and recomputed only after the index changes.

---

## 📑 Contextual Chunking

Standard text splitters segment documents at fixed character boundaries. This often separates clauses from their document titles or regulatory codes, eroding retrieval accuracy.

The `src/rag/document_loader.py` module applies **Contextual Chunking**:
1. Scans the first lines of the document for `DOCUMENT:` / `DOKÜMAN:` and `CODE:` / `KOD:` markers to build a header:
   - Example: `[Document: NovaTech Information Security Policy | CODE: SEC-POL-04]`
2. Injects this header **at the beginning of every chunk produced from that document**:
   ```text
   [Document: NovaTech Information Security Policy | CODE: SEC-POL-04]
   Clause 4.1: USB drive usage on corporate computers requires prior IT authorization...
   ```
3. The embedding model therefore retains the parent document identity for every passage. Chunk size and overlap are configurable (`CHUNK_SIZE`, `CHUNK_OVERLAP`).

---

## 🤖 Multi-Agent Workflow (`src/agent/multi_agent/`)

All queries (`/api/v1/query` and `/api/v1/query-stream`) run through the same compiled LangGraph `StateGraph` built by `MultiAgentOrchestrator`:

```text
supervisor ──► doc_agent | db_agent | compliance_agent | <custom agents> ──► record_turn ──► END
     └──────────────────── direct answer (greeting / meta question) ─────────┘
```

1. **`supervisor` (`SupervisorAgent.route`):**
   - If the request names an agent (`forced_agent`, from the API `agent` field), routes there without calling the LLM.
   - Messages consisting only of greeting words (e.g. "Merhaba", "hi there") are answered directly via a fast path. Mixed messages such as "hi, list sales" go through normal routing.
   - Otherwise the LLM receives the registered agents' descriptions, each agent's live routing context (`get_routing_context()`; `db_agent` lists the connected tables and columns, refreshed every 5 minutes), and the last turns of the conversation, and returns a JSON routing decision. If the JSON cannot be parsed, keyword heuristics pick the agent; unknown agent names fall back to `doc_agent`.
2. **Specialist sub-agent** (see [Custom Agents Guide](custom_agents_guide.md) for the contract).
3. **`record_turn`:** appends `{question, answer, agent}` to `chat_history` (trimmed to `CHAT_HISTORY_MAX_TURNS`, default 20) and sets `active_agent`.

`MultiAgentState` declares every key the graph carries. LangGraph drops keys that are not declared, so new state fields must be added there.

### Built-in Specialists

| Agent | Workflow |
| :--- | :--- |
| **`doc_agent`** | Query rewrite (for follow-ups) → two-stage retrieval → grounded generation → **Self-RAG guard** (below). |
| **`db_agent`** | Schema inspection → SQL generation (with recent conversation for follow-ups) → first statement extracted with `sqlparse` → guarded read-only execution → LLM summary of the rows. |
| **`compliance_agent`** | Policy retrieval → structured audit report with a `[COMPLIANT]` / `[WARNING]` / `[VIOLATION]` / `[UNDETERMINED]` verdict. If no policy passes the relevance gate, it returns `[UNDETERMINED]` without calling the LLM; the prompt also requires `[UNDETERMINED]` when the retrieved policies do not address the scenario. |

### Self-RAG Hallucination Guard (`doc_agent`)
1. **Generate** a draft answer from the retrieved context.
2. **Grade** it with `SYSTEM_PROMPT_GRADER`. The verdict passes only if its first word is `yes` / `evet`. If the grader itself fails, the answer counts as **unverified** (fail closed).
3. **Refine** once if the grade fails: unsupported claims are pruned (`SYSTEM_PROMPT_REFINE`) and the result is graded again.
4. **Fallback:** if the refined answer still fails, the safe `FALLBACK_RESPONSE` is returned.

The verdict and refinement flag are returned as `hallucination_grade` and `is_refined`.

> [!NOTE]
> `src/agent/agent_graph.py` (`EnterpriseRAGAgent`) contains the earlier single-agent Self-RAG graph (`rewrite → retrieve → generate → grade → refine/fallback`). It is kept as a library component and covered by tests, but the API does not use it for queries and it is not loaded at startup.

---

## 🧠 Multi-Turn Conversational Memory & Checkpointing

1. **SQLite Checkpointer (`data/multi_agent_conversations.db`):**
   - The workflow is compiled with LangGraph's `SqliteSaver`. `chat_history` persists across turns; all other state keys (answer, sources, trace, forced agent) are reset at the start of every turn.
   - Falls back to an in-memory checkpointer if SQLite initialization fails.
   - Requests without a `session_id` run on a checkpointer-less copy of the graph (single-turn, nothing persisted).
2. **User-Isolated Session Threads:**
   - Thread keys are partitioned by username: `thread_id = f"{username}_{session_id}"`, so users cannot read or poison another user's conversation.
3. **Conversation-Aware Agents:**
   - The supervisor sees recent turns when routing, `doc_agent` rewrites follow-up questions into standalone search queries (`SYSTEM_PROMPT_REWRITE`), and `db_agent` passes recent turns to SQL generation. Example: *"What is its unit price?"* after *"Which product has the highest stock?"* resolves "its" to the product from the previous answer.
4. **Retention:** `POST /api/v1/admin/cleanup-sessions?max_age_days=N` deletes threads whose most recent checkpoint is older than `N` days (`src/agent/multi_agent/sessions.py`).

### Streaming
`stream_events()` executes the same graph with `stream_mode="updates"` and converts node updates into NDJSON events (`status`, `agent_selected`, `sources`, `done`). If the client disconnects, the API stops the worker before the next node and keeps the concurrency gate until inference has actually finished, so Ollama never receives more than `OLLAMA_NUM_PARALLEL` concurrent requests.

---

## 🛡️ Enterprise Infrastructure & Security Architecture

### 1. Authentication, RBAC & Token Lifecycle
* **Dual JWT Token Lifecycle:**
  - **Access Token:** Short-lived HMAC-SHA256 Bearer token (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 60) used for API authorization.
  - **Refresh Token:** Long-lived token (`REFRESH_TOKEN_EXPIRE_DAYS`, default 7) exchanged via `POST /api/v1/auth/refresh`.
  - Tokens carry a `type` claim; refresh tokens are rejected as bearer credentials and vice versa.
* **Token Revocation:** Each user has a `token_version`, embedded in every token. Changing a password or disabling an account increments it, which invalidates all previously issued access and refresh tokens.
* **Dynamic Secret Management:** If `JWT_SECRET_KEY` is not set, a random 256-bit secret is generated and persisted in `data/.jwt_secret` (owner read/write only, `0600`, on POSIX systems) so tokens survive restarts without committing secrets to git.
* **Default Password Replacement:** Accounts using the built-in `admin123` password are flagged `must_change_password`. Until the password is changed via `POST /api/v1/auth/change-password`, every other endpoint returns HTTP 403 (`REQUIRE_DEFAULT_PASSWORD_CHANGE`, default `true`).
* **Configurable Password Policy (`PasswordPolicy`):** Enforced on user creation, admin password resets, and self-service password changes (minimum length, uppercase, lowercase, digit, optional special character).
* **Login Brute-Force Protection:** After `LOGIN_MAX_FAILED_ATTEMPTS` (default 5) failures within `LOGIN_LOCKOUT_WINDOW_SECONDS` (default 900), the account is temporarily locked (HTTP 429). The lock is per username, so users behind a shared gateway do not lock each other out.
* **Bcrypt Password Hashing:** Salted hashes stored locally in `data/users.json`. Plaintext passwords are never persisted or logged.
* **Three-Tier Authorization Model:**
  * `admin`: Complete administrative privileges (user management, ad-hoc SQL, table ETL sync, audit inspection and verification, backup/restore, session cleanup).
  * `editor`: Document management (upload, delete) and assistant queries.
  * `viewer`: Assistant queries, statistics, and database connection status.

### 2. Tamper-Evident Compliance Audit Trail (`src.core.audit`)
* **Structured SQLite Storage (`data/audit.db`):** Records logins (including failures and lockouts), token refreshes, password changes, queries, stream queries, document uploads/deletions, SQL queries, ETL syncs, feedback, backups, restores, and session cleanups.
* **Metadata Captured:** ISO timestamp, username, role, action, detail, cited sources, answer preview, client IP, duration (ms), and status (`success`, `error`, `denied`, `warning`, `cancelled`).
* **Hash Chain:** Every entry stores `prev_hash` and `entry_hash = SHA-256(prev_hash + entry content)`. Writes take an exclusive SQLite transaction (`BEGIN IMMEDIATE`) so concurrent writers cannot fork the chain.
* **Verification:** `GET /api/v1/admin/audit-verify` recomputes the chain and reports the first edited or deleted entry. Truncating the newest entries or rewriting the whole chain can only be detected against a previously exported `head_hash`, so store it outside the server periodically. Entries written before hash chaining existed are reported as unverifiable legacy entries.
* **Zero Cloud Leakage:** Audit logs reside strictly on local storage.

### 3. LLM Serving (Ollama) & Concurrency Protection
* **Separate server:** The LLM runs in an [Ollama](https://ollama.com) server (`OLLAMA_BASE_URL`, default model `qwen2.5:7b`). The API process loads no LLM weights, so it starts quickly, and switching models is a matter of `ollama pull <model>` plus `OLLAMA_MODEL`.
* **Explicit context window:** Requests set `num_ctx` (`OLLAMA_NUM_CTX`, default 4096) because some Ollama versions default to 2048 tokens and silently drop the beginning of longer prompts, i.e. the system prompt and retrieved context.
* **Availability check:** At startup the API checks that the server is reachable and the model is pulled, and logs an actionable error (`ollama pull …`) otherwise. The API still starts, so documents, users, and the audit log remain usable; `GET /api/v1/stats` reports the state as `llm_status`.
* **Concurrency:** Queries are capped by `asyncio.Semaphore(OLLAMA_NUM_PARALLEL)`. Match it to the server's own `OLLAMA_NUM_PARALLEL` setting.
* **Model choice is measured:** on the evaluation set, `qwen2.5:7b` answers 95% of the questions correctly versus 73% for the previous in-process 1.5B model (see [Evaluation](evaluation.md#-current-results)).

### 4. File Upload Hardening & Path Traversal Prevention
* **Path Traversal Protection:** `os.path.basename()` sanitization plus a canonical-path containment check (`os.path.commonpath`) against the data directory.
* **Extension Whitelist:** Uploads are restricted to `.pdf`, `.docx`, and `.txt`. Other files (`.exe`, `.sh`, `.py`, …) are rejected with HTTP 400.
* **Streaming Size Limit:** Uploads are written in 1 MB chunks up to `MAX_UPLOAD_SIZE_MB` (default 50). Oversized uploads are deleted and return HTTP 413.

### 5. Database Security (`src.connectors`)
Defense in depth, from application layer to database engine. See [Database Connectors](database_connectors.md#-strict-read-only-security-guard) for the full list.
* **Token-Level SQL Validation (`sqlparse`):** single statement only; must start with `SELECT` / `WITH`; data-, schema- and session-modifying keywords (`INSERT`, `DELETE`, `INTO`, `ATTACH`, `PRAGMA`, `SET`, …) and file/network/sleep functions (`pg_read_file`, `load_extension`, `pg_sleep`, …) are rejected. String literals are ignored, so values like `'Deleted'` do not cause false positives.
* **Table Allowlist (`DB_ALLOWED_TABLES`):** Table references are extracted from `FROM` lists (including comma joins), `JOIN`s, subqueries, and CTEs. Quoted and schema-qualified names are normalized.
* **Database-Enforced Read-Only Sessions:** SQLite connections run with `PRAGMA query_only = ON`; PostgreSQL queries run inside read-only transactions and MySQL/MariaDB sessions are read-only at session scope, both with a statement timeout (`DB_QUERY_TIMEOUT_SECONDS`). CI verifies this against real PostgreSQL and MySQL servers. For MSSQL/Oracle, use a SELECT-only database account.
* **Row Capping:** Result sets are capped at `DB_MAX_ROWS`.

### 6. Conversation Session Retention (`src.agent.multi_agent.sessions`)
* Admin-triggered cleanup (`POST /api/v1/admin/cleanup-sessions`) reads each thread's latest checkpoint timestamp and deletes threads older than the retention window (default 30 days) with `SqliteSaver.delete_thread()`.

### 7. Vector Database Backup & Restore (`src.api.state`)
* **Snapshots:** `backup_vector_db()` copies the ChromaDB directory to `backups/vector_db_backup_<timestamp>` while index writes are paused.
* **Staged Restore:** `restore_vector_db()` copies the chosen snapshot to `vector_db.restore_pending` and never touches the open database. On the next startup, `apply_pending_restore()` moves the current database to `backups/pre_restore_<timestamp>` and swaps the snapshot in before ChromaDB is opened.
* **Name Validation:** Only plain backup directory names created by the backup endpoint are accepted.

### 8. Rate Limiting & DoS Protection
* **Sliding Window Middleware:** Limits requests to `RATE_LIMIT_PER_MINUTE` (default 30) per authenticated account, or per client IP for anonymous requests. Keying by account prevents all users behind the Streamlit container (a single IP) from sharing one budget.
* **Automated Throttling:** Excess requests receive HTTP 429 with a `Retry-After` header. `/health` and API docs are exempt. Idle entries are purged periodically.

### 9. Centralized Logging & Error Handling (`src.core.logger`)
* Leveled logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`) to the console and rotating log files (10 MB per file, 5 backups).
* User questions are logged only at `DEBUG` level; `INFO` logs record the user, session, agent, and question length.
* API clients receive generic error messages; exception details are written to the server log only.
