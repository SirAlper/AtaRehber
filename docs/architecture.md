# 🏗️ System Architecture & Engineering Principles

`OpenLocalRagAgents` is built upon **Two-Stage Retrieval**, a **LangGraph Multi-Agent Supervisor workflow**, **Role-Based Access Control (RBAC)**, and **Hash-Chained Audit Logging**, designed to execute 100% locally on private enterprise hardware without sending proprietary data to third-party cloud APIs.

---

## 📐 High-Level Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            Enterprise Client Layer                               │
│  React Web UI (8080) · Streamlit UI (8501)  │   External Workplace Apps / Bots   │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ HTTP REST (Bearer JWT), NDJSON stream
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

The diagram shows the three data-facing specialists; `request_agent` (service requests) runs in the same workflow. A single Ollama chat model client is created once (`get_chat_model()` in `src/api/state.py`) and shared by the supervisor and every sub-agent; the model itself runs in the Ollama server. Routing and answer grading can use their own models (`OLLAMA_ROUTER_MODEL`, `OLLAMA_GRADER_MODEL`); when these are empty, everything uses `OLLAMA_MODEL`.

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
* **Relevance Gate:** Passages scoring below `RAG_MIN_RERANKER_SCORE` (0–1, default `0.005`) are dropped. If none remain, the question gets no context, so `doc_agent` answers "not found in the organization's documents" and `compliance_agent` returns an `[UNDETERMINED]` verdict without calling the LLM. On the evaluation set this rejects all off-topic questions while keeping every answerable one.
* **Output:** The top `RERANKER_TOP_N` (default `4`) passages are concatenated into the LLM context.

Index writes are serialized with a write lock (also used by backups), and per-document chunk statistics are cached and recomputed only after the index changes.

### Document Access Control (`src/auth/document_access.py`)
Documents are visible to everyone unless they are restricted to user groups (for example `akademik`, `idari`). The groups of each restricted document are stored in `data/document_access.json` and mirrored into the metadata of its chunks (`acl_public=False`, `acl_<group>=True`), so the vector store filters **before** similarity search and reranking: a user never receives context from a document outside their groups. Chunks without the key (everything indexed before access control existed, and synced database tables) count as public, so no migration is needed. `admin` and `editor` manage documents and search all of them; `viewer` accounts search public documents and those shared with one of their groups, and restricted documents they cannot search are also left out of their document list and statistics. Changing a document's groups updates its chunks in place and explicitly revokes groups that lost access.

Guests search only the documents shared with `GUEST_DOCUMENT_GROUP` (the search scope `["*only", "ziyaretci"]` becomes the filter `{"acl_ziyaretci": true}`), so documents that are public to accounts stay internal. Documents shared with visitors are public information, so every account searches them as well.

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

**Laws and regulations** (at least three article headings such as `Madde 30 –`, `MADDE 1 –`, `Geçici Madde 47 –`, `Ek Madde 5 –`) are split by article instead:
* Every article is its own chunk, together with its title line, so a rule is never mixed with the end of the previous article. Articles longer than `ARTICLE_CHUNK_SIZE` (default 900 characters) are split into pieces.
* Every chunk starts with the document title and the article: `[YÜKSEKÖĞRETİM KANUNU | Madde 30 – Emeklilik yaş haddi]`. The article is also stored as `article` metadata and shown next to the source in the answer.
* Pieces of a long article repeat the line that introduces their list in parentheses, e.g. `(a) Kınama: … Kınama cezasını gerektiren eylemler şunlardır:)`, so a listed act keeps the penalty it belongs to.
* Footnotes of consolidated texts (`[12] … değiştirilmiştir`) and upper-case appendix tables after the last article (lists of amending laws) become separate chunks instead of being attached to the last article.
* Numbers written in words get their digits (`src/rag/turkish_numbers.py`): `en az elli beş puan` becomes `en az elli beş (55) puan`. Laws write most limits in words while transitional articles use digits, and a small model otherwise prefers the number it can see as digits. Numbers below ten ("bir yarıyıl"), ordinals ("elli beşinci"), words already followed by digits, and idioms ("yüz yüze", "yüz kızartıcı") are left alone.

When the context is assembled, chunks of transitional articles (`Geçici Madde …`) and footnotes are placed after the provisions in force, because the model leans on what it reads first; the returned sources keep the relevance order.

---

## 🤖 Multi-Agent Workflow (`src/agent/multi_agent/`)

All queries (`/api/v1/query` and `/api/v1/query-stream`) run through the same compiled LangGraph `StateGraph` built by `MultiAgentOrchestrator`:

```text
supervisor ──► plan: step 1 ──► step 2 ──► … (≤ MAX_AGENT_STEPS) ──► [synthesize] ──► record_turn ──► END
     │           each step: doc_agent | db_agent | compliance_agent | request_agent | <custom agents>
     │           a failing step may be handed to another agent (≤ MAX_AGENT_HANDOFFS)
     └──────────────────── direct answer (greeting / meta question) ───────────────────┘
```

1. **`supervisor` (`SupervisorAgent.route`)** produces a **plan**: one step per agent, each with its own self-contained sub-question.
   - If the request names an agent (`forced_agent`, from the API `agent` field), the plan is that agent, without calling the LLM.
   - A short yes/no reply to a drafted service request goes straight back to `request_agent` (see below).
   - Messages consisting only of greeting words (e.g. "Merhaba", "hi there") are answered directly via a fast path. Mixed messages such as "hi, list sales" go through normal routing.
   - Otherwise the routing model receives the **available** agents' descriptions (agents whose `is_available()` is false, e.g. `db_agent` without a database, are left out), each agent's live routing context (`get_routing_context()`; `db_agent` lists the connected tables and columns, refreshed every 5 minutes), and the last turns of the conversation, and returns JSON steps. Most questions get one step; a composite question ("what does the regulation allow, and how many did I use?") gets up to `MAX_AGENT_STEPS` (default 3). The rules send every question about what a law, regulation, or document says to `doc_agent`, even when it asks "how many". Steps for unknown or unavailable agents fall back to `doc_agent`; if the JSON cannot be parsed, keyword heuristics (limited to available agents) pick one agent.
2. **Specialist steps** run one after another; each agent sees its own sub-question (see [Custom Agents Guide](custom_agents_guide.md) for the contract).
3. **Handoff:** when a step ends with a trace status the agent maps to another agent (`handoff_on`; `db_agent` maps `rejected`, `error`, and `not_connected` to `doc_agent`), or when an agent returns `{"handoff": {"to": …}}`, the same question is given to that agent once (`MAX_AGENT_HANDOFFS`, default 1). The failed step no longer counts for the answer, an agent never receives the same question twice in a turn, and unavailable agents are never targets. The trace records the handoff.
4. **`synthesize`** (only when more than one step produced an answer) merges the partial answers with `SYSTEM_PROMPT_SYNTHESIS`. The grading model then checks the merged text against the partial answers; if it adds or changes anything, the partial answers are shown one after another instead. The merged answer counts as verified only if every graded part passed. Sources are merged.
5. **`record_turn`:** appends `{question, answer, agent}` to `chat_history` (trimmed to `CHAT_HISTORY_MAX_TURNS`, default 20) and sets `active_agent` (the step's agent, `multi_agent` for merged answers, `supervisor` for direct replies). Results also list every contributing agent as `agents`.

`MultiAgentState` declares every key the graph carries. LangGraph drops keys that are not declared, so new state fields must be added there. The asking user (`username`, `role`, `groups`) is part of the state, so agents can filter documents and file requests on the user's behalf.

### Built-in Specialists

| Agent | Workflow |
| :--- | :--- |
| **`doc_agent`** | Query rewrite (for follow-ups) → two-stage retrieval → grounded generation → **Self-RAG guard** (below). |
| **`db_agent`** | Schema inspection → SQL generation (with recent conversation for follow-ups) → first statement extracted with `sqlparse` → guarded read-only execution → LLM summary of the rows. |
| **`compliance_agent`** | Rule retrieval → structured audit report with a `[COMPLIANT]` / `[WARNING]` / `[VIOLATION]` / `[UNDETERMINED]` verdict. If no rule passes the relevance gate, it returns `[UNDETERMINED]` without calling the LLM; the prompt also requires `[UNDETERMINED]` when the retrieved rules do not address the scenario. The prompt is organization-neutral: it cites articles or policy codes and names approving units only as the documents do. |
| **`request_agent`** | Service requests: extracts category, title, and details from the message, shows the draft, and files it in `data/requests.db` only after the user replies yes (the draft is kept as `pending_request` in the conversation state; any other message discards it). Without a session there is no next message, so the request is filed directly. Also lists the user's own requests. See [Service Requests](#5b-service-requests-srcservicesservice_requests). |

`db_agent` does not show database errors to the user (they can reveal schema details); the error stays in the trace and the question is handed to `doc_agent`.

### Answering Regulations
The document prompt tells the model to give the general rule before exceptions ("ancak", "hariç"), to prefer provisions in force over transitional articles ("Geçici Madde"), footnotes, and amendment notes, and to cite the article it used. Evaluation on a real law showed these as the most common errors (see [Evaluation](evaluation.md)). `ORGANIZATION_NAME` puts the institution's name into the prompts.

### Response Language (`src/agent/language.py`)
Every agent answers in the language of the question. `response_language()` detects Turkish or English from common words, Turkish characters, and Turkish verb suffixes; other languages are recognized by their script or function words and marked as "other". A question without cues (for example only a ticket code) inherits the language of the session's earlier questions, and English is the default. For Turkish and English, LLM prompts name the target language explicitly ("Write your entire response in Turkish…"), because a model tends to switch to English when the retrieved documents, the table rows, or the prompt template are English; for other languages the prompt asks for the question's language. See [Language Support](language_support.md) for the supported languages and the ones coming next. Fixed answers (not found, cannot be verified, greeting, database and compliance errors) exist in both languages. The compliance report template is localized as well (models copy template headings verbatim instead of translating them), while the verdict labels (`[VIOLATION / PROHIBITED]`, …) stay in English so they remain machine-readable.

### Custom Agents (`src/agent/multi_agent/custom_agents.py`)
Admins define agents in the web UI: a purpose (the supervisor routes by it), instructions, and tools (`documents`, `calculator`, `dates`, `database`; `src/agent/multi_agent/tools.py`). A `CustomAgent` is registered like a built-in agent; the model calls its tools through Ollama tool calling (at most 4 rounds). Fixed rules are added to every custom prompt, and an answer that used the documents passes the Self-RAG guard below with all tool results as context. See the [Custom Agents Guide](custom_agents_guide.md#-agents-without-code-web-ui).

### Self-RAG Hallucination Guard (`doc_agent`)
1. **Generate** a draft answer from the retrieved context.
2. **Grade** it, using the grading model (`OLLAMA_GRADER_MODEL`, default: the answer model). With `GRADER_MODE=quotes` (default) the grader (`SYSTEM_PROMPT_GRADER_QUOTES`, JSON output) says whether the answer's key facts are supported and copies, for each, the words of the context that state it (at most 4 quotes of 25 words). `grade_from_quotes()` then checks the copies against the context: the answer passes only if the grader says `yes` and every quote's words (at least 80%) occur in the context, so a quote the model made up fails the answer. With `GRADER_MODE=simple` the grader (`SYSTEM_PROMPT_GRADER`) answers only yes/no. The verdict passes only if its first word is `yes` / `evet`. If the grader itself fails, the answer counts as **unverified** (fail closed).
   * The grader writes its verdict first (`{"supported": …, "problem": …, "quotes": […]}`), so a reply cut off by the token limit still has one. If Ollama aborts the JSON-mode reply (the model repeating a token), the grader is asked once more without JSON mode.
   * A `no` whose `problem` is a phrase the context states word for word (e.g. `azami yedi yıl`) is treated as a grader mistake, since the prompt asks for a fact missing from the context. The answer then passes only if every number in it also occurs in the context or the question, so an invented number is still caught; computed numbers (e.g. a year the question asks to work out) keep the `no`.
3. **Refine** once if the grade fails: unsupported claims are pruned (`SYSTEM_PROMPT_REFINE`) and the result is graded again. The grader's objection is passed to the editor ("Auditor's objection: …"), which corrects that claim and keeps the other supported facts; it answers that the information is not in the documents only if the context has nothing that answers the question.
4. **Fallback:** if the refined answer still fails, the safe `FALLBACK_RESPONSE` is returned.

The verdict and refinement flag are returned as `hallucination_grade` and `is_refined`.

### Answer check (`src/agent/verification.py`)
`doc_agent` and custom agents check every answer based on documents with `verify_answer()`:
1. **Grader verdict** with quotes (step 2 above). A rejection gets a **second opinion** (`GRADER_SECOND_OPINION`): the grader is shown the first objection and asked to check it against the context, since the 7B grader rejects correct answers now and then.
2. **Code checks** the grader cannot be trusted with:
   * **Numbers** (`GRADER_NUMBER_CHECK`): every number of the answer (references such as "Madde 30" or "2547 sayılı" left out) must be in the grader's quotes (digits or words), the question, or a tool result. The grader may quote the right sentence and still accept "30 days" where it says "15 days".
   * **Transitional articles** (`GRADER_TRANSITIONAL_CHECK`): if all evidence comes from a `Geçici Madde` or footnote while a provision in force was also retrieved, the answer is sent back once with that objection (superseded values such as "65 points" instead of the "55 points" in force). If the refined answer still relies on it, it is shown with a warning.
3. A failed check is **refined once** with the objection and checked again.
4. Still failed: the sentences of the answer the quotes support (all their numbers quoted, or most word stems) are shown as a **partial answer**; if none are, the safe fallback.

The outcome travels with the answer as `verification: {"level": "verified" | "partial" | "unverified", "issues": [...]}` (issues: `transitional`, `partial`); a combined answer gets the weakest level of its parts. The web UI shows 🛡️ verified, ⚠️ partly verified, or "could not be verified" with the sections that may help. Answers that are not verified are recorded with status `warning` in the audit trail and listed for admins with the answers users rated down (`GET /api/v1/admin/review`, "Answers to Review" in the sidebar), which shows where the documents do not answer clearly.

A stronger grader than the answer model catches more of what the 7B model shares blind spots on; set `OLLAMA_GRADER_MODEL` when the GPU has room for a second model (it does not on a 6 GB card).

### Around the guard (`doc_agent`)
* **Follow-up questions:** with a conversation, short questions (up to 6 words, "Peki doktora için?") and questions that refer back ("bunun", "that") are rewritten into a standalone search query first; long standalone questions are searched as asked (`needs_rewrite()`).
* **Evidence:** the grader's quotes that really occur in the context are matched to the sentences of the sources they were copied from (`src/rag/evidence.py`); a verified answer's sources carry them as `evidence` (`[{"text", "citation"}]`, the citation with article and paragraph, e.g. `Madde 30/2`) and `used: true`, used sources first. The web UI shows them as "📌 Evidence" under the answer.
* **Answer cache:** verified answers to first questions of a conversation are reused for the same question (ignoring case, spacing, and final punctuation) and the same document access while the index is unchanged (`src/agent/answer_cache.py`, `ANSWER_CACHE_SIZE`, `ANSWER_CACHE_MINUTES`). `RAGEngine.index_version` changes on every upload, deletion, and access change, so no answer built on old documents or other access is reused. A reused answer is recorded as `cache_hit` in the trace.
* **Progress:** agents report their stage with `report_progress()` (`searching`, `writing`, `verifying`, `refining`); `stream_events()` passes them on as `progress` events, and the web UI shows them while it waits.
* **Experimental, off by default:** `ANSWER_EVIDENCE_FIRST` makes the model copy its evidence before answering (`EVIDENCE:` / `ANSWER:` lines, `split_evidence()`); `DOC_AGENT_TOOLS` lets it call the calculator and date tools, whose results become context for the check. See [Evaluation](evaluation.md) for their measured effect.

---

## 🧠 Multi-Turn Conversational Memory & Checkpointing

1. **SQLite Checkpointer (`data/multi_agent_conversations.db`):**
   - The workflow is compiled with LangGraph's `SqliteSaver`. `chat_history` and a drafted service request (`pending_request`) persist across turns; all other state keys (answer, sources, trace, plan, forced agent, user) are reset at the start of every turn.
   - Falls back to an in-memory checkpointer if SQLite initialization fails.
   - Requests without a `session_id` run on a checkpointer-less copy of the graph (single-turn, nothing persisted).
2. **User-Isolated Session Threads:**
   - Thread keys are partitioned by username: `thread_id = f"{username}_{session_id}"`, so users cannot read or poison another user's conversation.
3. **Conversation-Aware Agents:**
   - The supervisor sees recent turns when routing, `doc_agent` rewrites follow-up questions into standalone search queries (`SYSTEM_PROMPT_REWRITE`), and `db_agent` passes recent turns to SQL generation. Example: *"What is its unit price?"* after *"Which product has the highest stock?"* resolves "its" to the product from the previous answer.
4. **Retention:** `POST /api/v1/admin/cleanup-sessions?max_age_days=N` deletes threads whose most recent checkpoint is older than `N` days (`src/agent/multi_agent/sessions.py`).

### Streaming
`stream_events()` executes the same graph with `stream_mode="updates"` and converts node updates into NDJSON events (`status`, `agent_selected` for every step, `plan` for multi-step plans, `handoff`, `sources`, `done`). If the client disconnects, the API stops the worker before the next node and keeps the concurrency gate until inference has actually finished, so Ollama never receives more than `OLLAMA_NUM_PARALLEL` concurrent requests.

---

## 🛡️ Enterprise Infrastructure & Security Architecture

### 1. Authentication, RBAC & Token Lifecycle
* **Dual JWT Token Lifecycle:**
  - **Access Token:** Short-lived HMAC-SHA256 Bearer token (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 60) used for API authorization.
  - **Refresh Token:** Long-lived token (`REFRESH_TOKEN_EXPIRE_DAYS`, default 7) exchanged via `POST /api/v1/auth/refresh`.
  - Tokens carry a `type` claim; refresh tokens are rejected as bearer credentials and vice versa.
  - **Browser clients:** the React web UI sends `X-Token-Transport: cookie`, so the refresh token arrives as an `HttpOnly`, `SameSite=Strict` cookie scoped to `/api/v1/auth` (`Secure` with `REFRESH_COOKIE_SECURE=true`) instead of in the body. The access token is kept in memory only, so no token is in browser storage where an injected script could read it. Details: [API Reference](api_reference.md#12-refresh-access-token-post-apiv1authrefresh).
* **Token Revocation:** Each user has a `token_version`, embedded in every token. Changing a password or disabling an account increments it, which invalidates all previously issued access and refresh tokens.
* **Dynamic Secret Management:** If `JWT_SECRET_KEY` is not set, a random 256-bit secret is generated and persisted in `data/.jwt_secret` (owner read/write only, `0600`, on POSIX systems) so tokens survive restarts without committing secrets to git.
* **Default Password Replacement:** Accounts using the built-in `admin123` password are flagged `must_change_password`. Until the password is changed via `POST /api/v1/auth/change-password`, every other endpoint returns HTTP 403 (`REQUIRE_DEFAULT_PASSWORD_CHANGE`, default `true`).
* **Configurable Password Policy (`PasswordPolicy`):** Enforced on user creation, admin password resets, and self-service password changes (minimum length, uppercase, lowercase, digit, optional special character).
* **Login Brute-Force Protection:** After `LOGIN_MAX_FAILED_ATTEMPTS` (default 5) failures within `LOGIN_LOCKOUT_WINDOW_SECONDS` (default 900), the account is temporarily locked (HTTP 429). The lock is per username, so users behind a shared gateway do not lock each other out.
* **Bcrypt Password Hashing:** Salted hashes stored locally in `data/users.json`. Plaintext passwords are never persisted or logged.
* **Three-Tier Authorization Model:**
  * `admin`: Complete administrative privileges (user management and user groups, ad-hoc SQL, table ETL sync, audit inspection and verification, backup/restore, session cleanup).
  * `editor`: Document management (upload, delete, access groups), working off service requests, and assistant queries.
  * `viewer`: Assistant queries on the documents their groups may see, their own service requests, statistics, and database connection status.
  * `guest` (visitors without an account, `GUEST_ACCESS_ENABLED`): questions to `doc_agent` about the documents shared with `GUEST_DOCUMENT_GROUP` (default `ziyaretci`) only, with their own question budget per session (`GUEST_RATE_LIMIT_PER_MINUTE`). Guest sessions (`POST /api/v1/auth/guest`) exist only in their token, cannot be refreshed, end after `GUEST_SESSION_MINUTES`, and all end when guest access is turned off; accounts cannot be given the `guest` role.
* **User groups:** accounts carry a list of groups (`groups`, lowercase letters, digits, underscores) that decide which restricted documents a viewer can search (see [Document Access Control](#document-access-control-srcauthdocument_accesspy)).

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
* **Concurrency:** Queries are capped by `asyncio.Semaphore(OLLAMA_NUM_PARALLEL)`. Match it to the server's own `OLLAMA_NUM_PARALLEL` setting. At most `MAX_QUEUED_QUERIES` (default 10) further questions wait for a slot; beyond that the API answers HTTP 503 at once and the web UI says the assistant is busy, instead of a timeout after 180 s. A good value is about 180 s divided by the seconds a question takes, minus `OLLAMA_NUM_PARALLEL`.
* **Model choice is measured:** on the evaluation set, `qwen2.5:7b` answers 95% of the questions correctly versus 73% for the previous in-process 1.5B model (see [Evaluation](evaluation.md#-current-results)).

### 4. Transport Security & Telemetry
* **HTTPS:** `docker-compose.https.yml` puts an nginx reverse proxy with TLS, HSTS, and security headers in front of the UI and API and stops publishing the backend and UI ports ([Docker Deployment](docker_deployment.md#-https-reverse-proxy)).
* **No telemetry:** ChromaDB's anonymized telemetry is disabled in code, Streamlit usage statistics are disabled (`.streamlit/config.toml`, and an environment variable in the Docker image), and the Hugging Face Hub runs in offline mode once the models are downloaded.

### 4b. File Upload Hardening & Path Traversal Prevention
* **Path Traversal Protection:** `os.path.basename()` sanitization plus a canonical-path containment check (`os.path.commonpath`) against the data directory.
* **Extension Whitelist:** Uploads are restricted to `.pdf`, `.docx`, and `.txt`. Other files (`.exe`, `.sh`, `.py`, …) are rejected with HTTP 400.
* **Streaming Size Limit:** Uploads are written in 1 MB chunks up to `MAX_UPLOAD_SIZE_MB` (default 50). Oversized uploads are deleted and return HTTP 413.

### 5. Database Security (`src.connectors`)
Defense in depth, from application layer to database engine. See [Database Connectors](database_connectors.md#-strict-read-only-security-guard) for the full list.
* **Token-Level SQL Validation (`sqlparse`):** single statement only; must start with `SELECT` / `WITH`; data-, schema- and session-modifying keywords (`INSERT`, `DELETE`, `INTO`, `ATTACH`, `PRAGMA`, `SET`, …) and file/network/sleep functions (`pg_read_file`, `load_extension`, `pg_sleep`, …) are rejected. String literals are ignored, so values like `'Deleted'` do not cause false positives.
* **Table Allowlist (`DB_ALLOWED_TABLES`):** Table references are extracted from `FROM` lists (including comma joins), `JOIN`s, subqueries, and CTEs. Quoted and schema-qualified names are normalized.
* **Database-Enforced Read-Only Sessions:** SQLite connections run with `PRAGMA query_only = ON`; PostgreSQL queries run inside read-only transactions and MySQL/MariaDB sessions are read-only at session scope, both with a statement timeout (`DB_QUERY_TIMEOUT_SECONDS`). CI verifies this against real PostgreSQL and MySQL servers. For MSSQL/Oracle, use a SELECT-only database account.
* **Row Capping:** Result sets are capped at `DB_MAX_ROWS`.

### 5b. Service Requests (`src.services.service_requests`)
* **Storage:** `data/requests.db` (SQLite, part of full backups) with category, title, description, status (`open`, `in_progress`, `resolved`, `rejected`, `cancelled`), resolution note, and who changed it.
* **Access:** everyone files requests (through the chat or `POST /api/v1/requests`) and lists their own; staff (`admin`, `editor`) list all and change status; requesters can only cancel their own open requests. Other users' requests answer 404. Every change is audited (`request_create`, `request_update`).
* **E-mail (`src.services.notifier`):** off unless `SMTP_HOST` is set. New requests are e-mailed through the organization's own mail server to the address configured for the category in `REQUEST_NOTIFY_EMAILS` (or its `default`), never to an address from the conversation or the model. `REQUEST_NOTIFY_INCLUDE_DETAILS=false` sends only the request number and category.
* **No other side effects:** the assistant has no internet access and no other write actions.
* **Retention:** `REQUEST_RETENTION_DAYS` deletes closed requests during scheduled maintenance.

### 6. Conversation Session Retention (`src.agent.multi_agent.sessions`)
* Admin-triggered cleanup (`POST /api/v1/admin/cleanup-sessions`) reads each thread's latest checkpoint timestamp and deletes threads older than the retention window (default 30 days) with `SqliteSaver.delete_thread()`.

### 7. Backups, Restore & Retention (`src.services.backups`, `src.api.maintenance`)
* **Full backups:** `backup_all()` writes `backups/full_backup_<timestamp>/` with the vector index (copied while index writes are paused) and the data directory. SQLite databases are copied with the SQLite backup API, so snapshots taken under load are consistent; the JWT secret is excluded.
* **Scheduled maintenance:** at startup and then hourly, the API applies `AUDIT_RETENTION_DAYS`, `SESSION_RETENTION_DAYS`, and `REQUEST_RETENTION_DAYS` and takes a full backup when `BACKUP_INTERVAL_HOURS` has passed since the newest one on disk (so restarts do not reset the schedule), keeping `BACKUP_KEEP` backups. Everything is off by default. See [Data Protection](data_protection.md).
* **Audit retention and the hash chain:** purging stores the hash of the newest deleted entry as the chain anchor (`audit_meta` table) and records the purge as a `retention_purge` entry, so the remaining chain is still verified end to end.
* **Staged Restore (index only):** `restore_vector_db()` copies the chosen snapshot (for full backups its `vector_db/` part) to `vector_db.restore_pending` and never touches the open database. On the next startup, `apply_pending_restore()` moves the current database to `backups/pre_restore_<timestamp>` and swaps the snapshot in before ChromaDB is opened.
* **Name Validation:** Only plain backup directory names created by the backup endpoint are accepted.

### 8. Rate Limiting & DoS Protection
* **Sliding Window Middleware:** Limits questions, uploads, and other changes to `RATE_LIMIT_PER_MINUTE` (default 30) and reads (`GET`) to `RATE_LIMIT_READS_PER_MINUTE` (default 300) per authenticated account, or per client IP for anonymous requests; the web UI reloads its panels with several reads on every click. Keying by account prevents all users behind the Streamlit container (a single IP) from sharing one budget.
* **Automated Throttling:** Excess requests receive HTTP 429 with a `Retry-After` header. `/health` and API docs are exempt. Idle entries are purged periodically.

### 9. Centralized Logging & Error Handling (`src.core.logger`)
* Leveled logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`) to the console and rotating log files (10 MB per file, 5 backups).
* User questions are logged only at `DEBUG` level; `INFO` logs record the user, session, agent, and question length.
* API clients receive generic error messages; exception details are written to the server log only.
