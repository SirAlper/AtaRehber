# 🔌 REST API Documentation

`AtaRehber` exposes a high-performance REST API built on **FastAPI** to enable turnkey integration with enterprise portals, CRM, ERP, and internal workplace bots.

The interactive OpenAPI Swagger UI is available at `http://localhost:8000/docs` whenever the server is running.

---

## 📋 Endpoints Overview

| Method | Endpoint | Required Role | Description |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/auth/login` | Public | Obtain signed JWT Bearer access token and refresh token |
| `POST` | `/api/v1/auth/refresh` | Public | Exchange refresh token for fresh access and refresh token pair |
| `POST` | `/api/v1/auth/logout` | Public | Delete the refresh token cookie of a browser client |
| `GET` | `/api/v1/auth/guest` | Public | Whether guest access is enabled (`{"enabled": true}`) |
| `POST` | `/api/v1/auth/guest` | Public | Start a guest session (visitors without an account; `GUEST_ACCESS_ENABLED`) |
| `GET` | `/api/v1/auth/me` | Authenticated | View current authenticated user profile |
| `POST` | `/api/v1/auth/register` | `admin` | Register new user account with password policy enforcement |
| `GET` | `/api/v1/auth/users` | `admin` | List all registered enterprise user accounts |
| `PATCH` | `/api/v1/auth/users/{username}` | `admin` | Update user status (disable/enable), role, document access groups, profile (unit, program, level), or reset password |
| `DELETE` | `/api/v1/auth/users/{username}` | `admin` | Permanently delete a registered user account |
| `GET` | `/api/v1/stats` | Authenticated | Hardware acceleration, active models, backend info, and index counts |
| `GET` | `/api/v1/documents` | Authenticated | List the documents the caller may search, with chunk counts and access groups |
| `POST` | `/api/v1/upload-file` | `admin`, `editor` | Upload new PDF, DOCX, or TXT document (optionally restricted to user groups) and auto-index into ChromaDB |
| `DELETE` | `/api/v1/documents/{filename}` | `admin`, `editor` | Permanently delete document from disk and purge chunks from vector store |
| `PUT` | `/api/v1/documents/{filename}/access` | `admin`, `editor` | Restrict a document to user groups, or make it visible to everyone |
| `GET` | `/api/v1/agents` | Authenticated | List the supervisor (`auto`) and the specialist sub-agents that are currently available |
| `POST` | `/api/v1/query` | Authenticated, `guest` | Multi-agent question answering with multi-turn session memory |
| `POST` | `/api/v1/query-stream` | Authenticated, `guest` | Same workflow as `/query`, streamed as NDJSON events |
| `POST` | `/api/v1/feedback` | Authenticated, `guest` | Submit thumbs-up/down evaluation on agent answers |
| `GET` | `/api/v1/requests` | Authenticated | List own service requests (staff: all with `all_users=true`) |
| `POST` | `/api/v1/requests` | Authenticated | File a service request without the chat (form) |
| `PATCH` | `/api/v1/requests/{request_id}` | Authenticated | Staff change a request's status; requesters cancel their own open requests |
| `GET` | `/api/v1/database/status` | Authenticated | Database connection status, dialect type, and schema summary |
| `POST` | `/api/v1/database/test-query` | `admin` | Execute safe read-only SELECT queries |
| `POST` | `/api/v1/database/sync-table` | `admin` | Convert database table rows into ChromaDB vector chunks |
| `GET` | `/api/v1/admin/audit-logs` | `admin` | Filter and inspect compliance audit trail logs |
| `GET` | `/api/v1/admin/audit-stats` | `admin` | Metrics summary (queries, uploads, logins, errors, feedback) |
| `GET` | `/api/v1/admin/audit-verify` | `admin` | Verify the audit trail hash chain and return its head hash |
| `POST` | `/api/v1/admin/cleanup-sessions`| `admin` | Prune conversation sessions older than specified age |
| `POST` | `/api/v1/admin/backup` | `admin` | Create a full backup: vector index plus data directory (documents, users, audit log, conversations) |
| `GET` | `/api/v1/admin/backups` | `admin` | List full and vector-index backups |
| `POST` | `/api/v1/admin/maintenance/run` | `admin` | Apply the retention periods and take a scheduled backup now (also runs hourly) |
| `POST` | `/api/v1/admin/restore` | `admin` | Stage a vector index restore from a backup (applied on next restart) |
| `GET` | `/api/v1/admin/review` | `admin`, `editor` | Recent answers that could not be (fully) verified or found, and answers rated down (answered ones left out) |
| `GET` | `/api/v1/admin/faq` | `admin`, `editor` | Staff answers to unanswered questions (FAQ) |
| `POST` | `/api/v1/admin/faq` | `admin`, `editor` | Answer a question: stored, searchable at once, shown to everyone who asked it |
| `PUT` | `/api/v1/admin/faq/{entry_id}` | `admin`, `editor` | Change a staff answer (shown again to the users who asked) |
| `DELETE` | `/api/v1/admin/faq/{entry_id}` | `admin`, `editor` | Delete a staff answer (no longer searched) |
| `GET` | `/api/v1/faq/answers` | Authenticated | Staff answers to the caller's questions they have not marked as seen |
| `POST` | `/api/v1/faq/answers/seen` | Authenticated | Mark staff answers as seen |
| `GET` | `/api/v1/admin/agent-stats` | `admin` | Per agent: questions, median and slow durations, unverified answers, errors, ratings |
| `GET` | `/api/v1/admin/agent-tools` | `admin` | Tools custom agents can use (labels in `language=tr` or `en`) and whether they work right now |
| `GET` | `/api/v1/admin/custom-agents` | `admin` | Custom agent definitions with their availability |
| `PUT` | `/api/v1/admin/custom-agents/{name}` | `admin` | Create or replace a custom agent; the supervisor can route to it at once |
| `DELETE` | `/api/v1/admin/custom-agents/{name}` | `admin` | Delete a custom agent |
| `POST` | `/api/v1/auth/change-password` | Authenticated | Change own password (required after first login with the default password) |
| `GET` | `/api/v1/ui-settings` | Public | The web UI's name, texts, and default language for this organization |
| `GET` | `/api/v1/admin/ui-settings` | `admin` | The stored web UI texts with who changed them last |
| `PUT` | `/api/v1/admin/ui-settings` | `admin` | Change the web UI's name and texts (empty: built-in text) |
| `GET` | `/health` | Public | Liveness probe for container healthchecks |

> [!NOTE]
> All protected endpoints require the HTTP header:  
> `Authorization: Bearer <your_access_token>`
>
> Error responses never contain internal exception details; they are written to the server log instead.

---

## 🔐 1. Authentication & User Management Endpoints

### 1.1 User Login (`POST /api/v1/auth/login`)
Authenticates credentials and issues a signed JWT Bearer access token valid for `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 60 minutes) and a long-lived refresh token valid for `REFRESH_TOKEN_EXPIRE_DAYS` (default: 7 days).

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{
       "username": "admin",
       "password": "admin123"
     }'
```

**Example Response (HTTP 200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "role": "admin",
  "username": "admin",
  "expires_in": 3600,
  "must_change_password": false
}
```

* Access tokens and refresh tokens are not interchangeable: a refresh token is rejected as a bearer credential.
* Changing a password or disabling an account revokes all previously issued tokens.
* After `LOGIN_MAX_FAILED_ATTEMPTS` (default 5) failed logins within `LOGIN_LOCKOUT_WINDOW_SECONDS` (default 900), the account is temporarily locked and login returns HTTP 429.
* If `must_change_password` is `true` (e.g. first login with the default `admin123`), every endpoint except `/auth/me` and `/auth/change-password` returns HTTP 403 until the password is changed.

### 1.1a Change Own Password (`POST /api/v1/auth/change-password`)
Validates the current password, applies the password policy, revokes existing tokens, and returns a fresh token pair.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/change-password" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"current_password": "admin123", "new_password": "N3w-Strong-Passw0rd"}'
```

---

### 1.2 Refresh Access Token (`POST /api/v1/auth/refresh`)
Exchange a valid refresh token for a fresh access token and rotated refresh token pair without re-entering credentials.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/refresh" \
     -H "Content-Type: application/json" \
     -d '{
       "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
     }'
```

**Example Response (HTTP 200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "role": "admin",
  "username": "admin",
  "expires_in": 3600,
  "must_change_password": false
}
```

The refresh token is rotated on every call. Refresh tokens issued before a password change or account deactivation are rejected with HTTP 401.

**Browser clients (refresh token in a cookie):** with the header `X-Token-Transport: cookie`, login, refresh, and change-password return `"refresh_token": null` and set the refresh token as the cookie `olr_refresh` instead (`HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`, valid for `REFRESH_TOKEN_EXPIRE_DAYS`; `Secure` when `REFRESH_COOKIE_SECURE=true`). Page scripts cannot read it, so a script injected into the page cannot steal the long-lived token. `POST /api/v1/auth/refresh` then needs no body: the browser sends the cookie. `POST /api/v1/auth/logout` deletes the cookie. The web UI keeps the access token in memory only. Clients without the header get the refresh token in the body as before.

---

### 1.2a Guest Sessions (`GET` / `POST /api/v1/auth/guest`)
Visitors without an account (for example prospective open education students) can ask questions when `GUEST_ACCESS_ENABLED=true`. `GET` returns `{"enabled": true|false}`; `POST` returns an access token for a new guest session (`role: "guest"`, username `guest-<random>`, no refresh token, valid for `GUEST_SESSION_MINUTES`, default 120). With guest access disabled, `POST` returns HTTP 404 and existing guest tokens are rejected.

Guests may only call `/api/v1/query`, `/api/v1/query-stream`, `/api/v1/feedback`, and `/api/v1/auth/me` (everything else answers HTTP 403):
* Their questions always go to `doc_agent` (a pure greeting gets a greeting): no database, service requests, or compliance checks.
* They search **only** the documents shared with `GUEST_DOCUMENT_GROUP` (default `ziyaretci`), not the documents public to accounts. Share a document with visitors by giving it that group (upload form or `PUT /api/v1/documents/{filename}/access`); every account sees those documents too.
* Each guest session has its own question budget, `GUEST_RATE_LIMIT_PER_MINUTE` (default 10), so visitors behind one IP do not block each other. Starting sessions is limited per IP like any anonymous request.
* Their questions are recorded in the audit trail under the session's username with role `guest`.

---

### 1.3 Current User Profile (`GET /api/v1/auth/me`)
Returns the profile and role of the caller identified by the JWT token. Also reachable while a password change is pending.

```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "username": "admin",
  "role": "admin",
  "disabled": false,
  "created_at": "2026-09-18T10:00:00",
  "must_change_password": false,
  "groups": [],
  "profile": {"unit": "Mühendislik Fakültesi", "program": "Bilgisayar Mühendisliği", "level": "3. sınıf"}
}
```

---

### 1.4 Register User (`POST /api/v1/auth/register`)
Registers a new enterprise user. Restricted to `admin` role.

* **Roles Available:** `admin`, `editor`, `viewer`
* **`groups`** *(optional)*: document access groups, e.g. `["akademik"]` (1-32 lowercase letters, digits, or underscores; names are lowercased). Viewers can search restricted documents only if they share a group with them.
* **`profile`** *(optional)*: where the user belongs, `{"unit": "...", "program": "...", "level": "..."}` (each optional, at most 100 characters; other keys return HTTP 400). Agents answer rules that differ by unit, program, or level for this user, and questions about "my department" are searched for the user's department.
* **Password Policy:** Passwords must meet configurable enterprise security rules (minimum 8 characters, uppercase, lowercase, and digit required by default). Violations return HTTP 400 with the list of unmet rules.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "username": "jane_analyst",
       "password": "SecurePassword123!",
       "role": "viewer",
       "groups": ["akademik"]
     }'
```

**Example Response (HTTP 201):**
```json
{
  "username": "jane_analyst",
  "role": "viewer",
  "disabled": false,
  "created_at": "2026-09-18T11:20:00",
  "must_change_password": false,
  "groups": ["akademik"]
}
```

---

### 1.5 List All Users (`GET /api/v1/auth/users`)
Lists all registered enterprise users. Restricted to `admin` role.

```bash
curl -X GET "http://localhost:8000/api/v1/auth/users" \
     -H "Authorization: Bearer <token>"
```

---

### 1.6 Update User (`PATCH /api/v1/auth/users/{username}`)
Modifies a user's role, status (enable/disable), document access groups, or resets their password. Restricted to `admin` role.

* `groups` replaces the user's groups (`[]` removes all); invalid group names return HTTP 400.
* `profile` replaces the user's unit, program, and level (`{}` clears them).
* New passwords are validated against the password policy (HTTP 400 on violation).
* Resetting the password or disabling the account revokes all of the user's existing tokens.

```bash
curl -X PATCH "http://localhost:8000/api/v1/auth/users/jane_analyst" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "role": "editor",
       "disabled": false,
       "groups": ["akademik", "idari"]
     }'
```

---

### 1.7 Delete User (`DELETE /api/v1/auth/users/{username}`)
Deletes a user account. The primary default administrator cannot be deleted. Restricted to `admin` role.

```bash
curl -X DELETE "http://localhost:8000/api/v1/auth/users/jane_analyst" \
     -H "Authorization: Bearer <token>"
```

---

## 📄 2. Document & System Endpoints

### 2.1 System Statistics (`GET /api/v1/stats`)
Returns the embedding and LLM models (answers, routing, grading), whether Ollama is ready (`llm_status`: `"ok"` or a problem with the fix, e.g. `"... Run: ollama pull qwen2.5:7b"`; every configured model must be pulled), the retrieval device, and vector collection statistics. Document counts only include documents the caller may search.

```bash
curl -X GET "http://localhost:8000/api/v1/stats" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "device": "CPU",
  "llm_backend": "ollama",
  "embedding_model": ".../models/bge-m3",
  "llm_model": "qwen2.5:7b",
  "router_model": "qwen2.5:7b",
  "grader_model": "qwen2.5:7b",
  "ollama_base_url": "http://localhost:11434",
  "llm_status": "ok",
  "total_chunks": 42,
  "total_documents": 3,
  "documents": {
    "NovaTech_Security_Policy.pdf": 14,
    "IT_Support_Runbook.docx": 18,
    "Company_FAQ.txt": 10
  },
  "database": {
    "status": "connected",
    "message": "Successfully connected (SQLITE).",
    "dialect": "sqlite",
    "tables": ["destek_talepleri", "satislar", "urunler"],
    "table_count": 3
  }
}
```

---

### 2.2 List Documents (`GET /api/v1/documents`)
Returns file metadata, vector chunk counts, and access groups (`[]`: visible to everyone) for the uploaded files in `data/`. Viewers only see public documents and documents shared with one of their groups; admins and editors see all.

```bash
curl -X GET "http://localhost:8000/api/v1/documents" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "count": 1,
  "documents": [
    {
      "filename": "NovaTech_Security_Policy.pdf",
      "size_kb": 124.5,
      "chunk_count": 14,
      "modified_at": "2026-09-18 10:15:22",
      "groups": ["idari"]
    }
  ]
}
```

---

### 2.3 Upload Document (`POST /api/v1/upload-file`)
Accepts multipart file upload, applies contextual chunking, and persists vectors to ChromaDB.

* **Required Role:** `admin` or `editor`
* **Supported Formats:** `.pdf`, `.docx`, `.txt`
* **Maximum Size:** Default 50 MB (`MAX_UPLOAD_SIZE_MB`)
* **Security:** Enforces filename sanitization (`os.path.basename`) and prevents path traversal.
* **Re-upload:** Uploading a file with an existing name replaces the file and its indexed chunks.
* If no text can be extracted (e.g. a scanned PDF), the file is kept and the response has `"status": "warning"` with `chunk_count: 0`.
* **`groups`** *(form field, optional)*: comma-separated user groups allowed to search the document, e.g. `idari, akademik`. Empty: visible to everyone. Invalid group names return HTTP 400.

```bash
curl -X POST "http://localhost:8000/api/v1/upload-file" \
     -H "Authorization: Bearer <token>" \
     -F "file=@NovaTech_Security_Policy.pdf" \
     -F "groups=idari"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "'NovaTech_Security_Policy.pdf' successfully uploaded and indexed.",
  "filename": "NovaTech_Security_Policy.pdf",
  "chunk_count": 14,
  "groups": ["idari"]
}
```

---

### 2.4 Delete Document (`DELETE /api/v1/documents/{filename}`)
Permanently deletes the file from `data/` and purges its vector embeddings from ChromaDB.

* **Required Role:** `admin` or `editor`

```bash
curl -X DELETE "http://localhost:8000/api/v1/documents/NovaTech_Security_Policy.pdf" \
     -H "Authorization: Bearer <token>"
```

Deleting a document also removes its access groups, so a later upload with the same name starts out public.

---

### 2.5 Set Document Access (`PUT /api/v1/documents/{filename}/access`)
Restricts an indexed document to user groups, or makes it visible to everyone with an empty list. The chunks are updated in place; groups that lose access are revoked explicitly. The change is audited as `document_access`.

* **Required Role:** `admin` or `editor`
* HTTP 404 if the document is not indexed, HTTP 400 for invalid group names.

```bash
curl -X PUT "http://localhost:8000/api/v1/documents/NovaTech_Security_Policy.pdf/access" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"groups": ["idari", "akademik"]}'
```

**Example Response:**
```json
{"status": "success", "filename": "NovaTech_Security_Policy.pdf", "groups": ["akademik", "idari"], "updated_chunks": 14}
```

---

## 🤖 3. AI Query Endpoints

### 3.0 List Agents (`GET /api/v1/agents`)
Returns the routing options for the `agent` query parameter: `auto` (supervisor routing) plus every specialist that is currently available. `db_agent` is only listed when a database is connected.

```bash
curl -X GET "http://localhost:8000/api/v1/agents" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "agents": [
    {"name": "auto", "display_name": "👑 Auto (Supervisor Orchestrator)", "description": "Automatically analyzes question intent and delegates to the best specialist sub-agent or responds directly.", "version": "2.0.0"},
    {"name": "doc_agent", "display_name": "Document & Regulation Specialist", "description": "Answers questions about what the organization's documents say: laws, regulations, policies, ...", "version": "1.0.0"},
    {"name": "db_agent", "display_name": "SQL & Database Analyst", "description": "Answers questions about the data stored in the connected database tables ...", "version": "1.0.0"},
    {"name": "compliance_agent", "display_name": "Compliance Auditor", "description": "Gives a formal verdict [COMPLIANT / WARNING / VIOLATION] on a specific action ...", "version": "1.0.0"},
    {"name": "request_agent", "display_name": "Service Request Agent", "description": "Opens a service request / ticket when the user explicitly asks to open, file, or report something ...", "version": "1.0.0"}
  ]
}
```

---

### 3.1 Batch Query (`POST /api/v1/query`)
Runs the multi-agent LangGraph workflow: the supervisor plans one or more specialist steps (or answers greetings directly), the specialists produce the answer (a failing step is handed to another agent once, several answers are combined), and the turn is saved to the session history. Documents are searched with the caller's access groups. See [Architecture](architecture.md#-multi-agent-workflow-srcagentmulti_agent) for details.

* **Busy server:** at most `MAX_QUEUED_QUERIES` (default 10) questions wait for the model; beyond that the API answers at once with HTTP 503 (`Retry-After: 60`) instead of letting the client time out (header `X-Error-Code: busy`). `/query-stream` checks this before streaming starts.
* **Language model down:** each question first checks that Ollama answers and has the configured models (`LLM_STATUS_CHECK`, result reused for `LLM_STATUS_CACHE_SECONDS`, default 10). If not, the API answers HTTP 503 with `X-Error-Code: llm_unavailable` and `"detail": "The language model is not available right now. Please try again later."` without running the agents; the web UI shows its own message for it. `/query-stream` checks this before streaming starts.

* **Request Parameters:**
  * `question` *(string, required)*: The user question (1-4000 characters).
  * `session_id` *(string, optional)*: Up to 64 characters of `[a-zA-Z0-9_-]`. Turns with the same `session_id` share conversation memory, stored per user in `data/multi_agent_conversations.db`. Without it, the query is single-turn and nothing is persisted.
  * `agent` *(string, optional)*: `auto` (default) for supervisor routing, or a registered agent name from `GET /api/v1/agents` (e.g. `doc_agent`, `db_agent`, `compliance_agent`, `request_agent`) to bypass routing. Unknown names fall back to supervisor routing.

```bash
curl -X POST "http://localhost:8000/api/v1/query" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "What is the password rotation policy for workstations?",
       "session_id": "session-user-123",
       "agent": "auto"
     }'
```

**Example Response:**
```json
{
  "status": "success",
  "answer": "According to the company information security policy, user passwords must be updated at least every 90 days.",
  "sources": [
    {
      "source": "NovaTech_Security_Policy.pdf",
      "chunk_index": 2,
      "content": "[Document: NovaTech Information Security | CODE: SEC-04]\nClause 3: User passwords must be updated every 90 days...",
      "page": 2,
      "distance": 0.421,
      "reranker_score": 0.9871
    }
  ],
  "active_agent": "doc_agent",
  "agents": ["doc_agent"],
  "agent_trace": [
    {"agent": "supervisor", "action": "intent_routing", "target_agent": "doc_agent", "reason": "Question about company policy", "duration_ms": 612, "status": "success", "timestamp": "2026-09-18T10:30:14+00:00"},
    {"agent": "doc_agent", "action": "retrieval_and_generation", "search_query": "workstation password rotation policy", "sources_count": 3, "hallucination_grade": "yes", "is_refined": false, "duration_ms": 2710, "status": "success", "timestamp": "2026-09-18T10:30:17+00:00"}
  ],
  "hallucination_grade": "yes",
  "is_refined": false
}
```

* **`active_agent`:** the agent that produced the answer (`supervisor` for direct answers, `multi_agent` when the answers of several agents were combined). **`agents`** lists every agent whose answer is part of the final answer.
* **Composite questions:** the supervisor may plan up to `MAX_AGENT_STEPS` steps; the trace then contains the plan (`intent_routing` entry with `plan`), one entry per agent, and a `synthesize` entry. If the combined text is not supported by the partial answers, the partial answers are returned one after another.
* **Handoffs:** when a step fails (for example `db_agent`'s query is rejected, or no database is connected), the question is given to `doc_agent` once; the trace contains a `handoff` entry with `from_agent`, `target_agent`, and `reason`. Database errors are never included in the answer.
* **Questions back (`clarification`):** in a conversation (`session_id`), a short question about the asker's own case whose answer depends on something they did not say gets one question back instead (`CLARIFY_QUESTIONS`, default `true`), e.g. *"Kaç gün izin hakkım var?"* when the rules differ by seniority (asked by `doc_agent` after reading the rules, or by the supervisor without a chosen `agent`). The response then has `"clarification": {"question": "...", "options": ["...", "..."]}` (`answer` holds the same text with the options as a list); otherwise `clarification` is `null`. The next message answers it: the supervisor routes the original question together with that answer, and never asks back twice in a row.
* **Steps that build on each other:** a plan step may name earlier steps it needs (`"uses": [0]` in the trace's `plan`, e.g. the product found in the database, then that product's return policy); it gets their answers. The combined answer may draw the conclusion the question asks for (compare, subtract, say whether a condition is met); the check accepts conclusions that follow from the parts.
* **Slow steps:** a step that takes longer than `AGENT_STEP_TIMEOUT_SECONDS` (default 180) is answered with *"This part could not be completed in time."* (trace action `timeout`); the other steps still count.
* **Service requests:** asking to open a request (e.g. *"B204'teki projektör çalışmıyor, arıza kaydı açar mısın?"*) makes `request_agent` show a draft and ask for confirmation; the next message *"evet"* files it (see [Service Requests](#-5b-service-request-endpoints)), *"hayır"* or any other message discards it. Without `session_id` the request is filed directly. Users can also cancel their own open requests from the chat (*"#12 numaralı talebimi iptal et"*, again after *"evet"*) and add information to them (*"Talebime ekle: B204 dersliği"*); without a number their only open request is meant, with several they are asked which one.
* **`sources[].page` / `page_end`:** PDF page the passage starts on, and the page it ends on if different. Absent for DOCX/TXT files and for documents indexed before page tracking (re-upload them to add pages).
* **`sources[].reranker_score`:** cross-encoder relevance from 0 to 1. Chunks below `RAG_MIN_RERANKER_SCORE` (default `0.005`) are never used or returned.
* **Response language:** answers follow the language of the question (Turkish or English; other languages on a best-effort basis with English fixed texts, see [Language Support](language_support.md)); a question without language cues, such as a bare ticket code, inherits the language of the session's earlier questions. The fixed texts below are shown in English; Turkish questions get the Turkish versions (e.g. *"Bu bilgi kurum dokümanlarında bulunmuyor."*). Compliance verdict labels such as `[VIOLATION / PROHIBITED]` stay in English in both languages.
* **No relevant documents:** if no chunk passes the relevance gate (among the documents the caller may search), `doc_agent` answers *"This information is not found in the organization's documents."* with empty `sources`, and `compliance_agent` returns an `[UNDETERMINED]` verdict. The LLM is not called in either case.
* **`hallucination_grade` / `is_refined`:** set by `doc_agent`'s Self-RAG guard. An unverifiable answer is replaced by *"This information cannot be fully verified against the organization's documents."* Other agents leave `hallucination_grade` empty; a combined answer is `yes` only if every graded part passed.
* **Checked database answers:** every number of a `db_agent` answer must be a value of the query result, the row count, or a number of the question (Turkish and English number formats, rounding allowed). A wrong number is corrected once; if it stays wrong, the result rows are shown as a table instead. Such answers carry `"verification": {"level": "verified", "issues": ["data"]}`.
* **Checked compliance verdicts:** the verdict and the rules it cites (not the risk analysis) must be stated in the retrieved rules. An unsupported verdict is revised once, then replaced by `[UNDETERMINED]` with the advice to ask the responsible unit (`verification.level` `unverified`). A supported verdict shows its evidence under the sources.
* **Unanswered questions:** a "not found" answer carries `"verification": {"level": "unverified", "issues": ["not_found"]}`, so it is listed for staff in `GET /api/v1/admin/review` to answer in the FAQ.
* **`db_agent` traces** include the executed `sql`, `row_count`, and `data_check` (`success`, `mismatch` when the rows were shown instead, or `error`).
* **LLM failing during a question:** the check above catches a stopped Ollama before the question runs. If it fails while a question runs, the request still returns HTTP 200 with a fallback answer (for `doc_agent` the *"cannot be fully verified"* text). `llm_status` in `GET /api/v1/stats` shows the current state.

---

### 3.2 Event Streaming Query (`POST /api/v1/query-stream`)
Runs the same workflow as `/api/v1/query` (same request body, same session memory) and streams progress as newline-delimited JSON (**NDJSON**).

```bash
curl -N -X POST "http://localhost:8000/api/v1/query-stream" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "How does the hardware replacement approval process work?",
       "session_id": "session-user-123"
     }'
```

**Delivered NDJSON Event Sequence (specialist answer):**
```json
{"type": "status", "message": "👑 Supervisor: Analyzing query and routing to the optimal specialist agent...", "node": "supervisor"}
{"type": "agent_selected", "agent": "doc_agent", "display_name": "Document & Regulation Specialist", "reason": "Task delegated to specialist: 'Document & Regulation Specialist'."}
{"type": "status", "message": "🤖 Document & Regulation Specialist: Executing specialized task...", "node": "doc_agent"}
{"type": "sources", "sources": [{"source": "IT_Support_Runbook.docx", "chunk_index": 1, "...": "..."}]}
{"type": "done", "answer": "...", "sources": [], "agent_trace": [], "active_agent": "doc_agent", "agents": ["doc_agent"], "hallucination_grade": "yes", "is_refined": false, "verification": {"level": "verified", "issues": []}, "clarification": null}
```

* For greetings answered by the supervisor, `agent_selected` has `"agent": "supervisor"` and no `sources` event is sent.
* Multi-step plans start with `{"type": "plan", "steps": [{"agent": "...", "question": "..."}]}`; every step sends its own `agent_selected`, `status`, and `sources` events.
* A handoff sends `{"type": "handoff", "from": "db_agent", "to": "doc_agent", "reason": "..."}` followed by the new agent's `agent_selected` event.
* On failure, an `{"type": "error", "message": "An internal error occurred while processing the query."}` event is sent before the stream ends. If the queue fills up between the check and the start of the stream, the event is `{"type": "error", "code": "busy", "message": "The assistant is busy. ..."}`.
* If the client disconnects, processing stops before the next workflow step and the query is audited with status `cancelled`.

---

### 3.3 Answer Evaluation Feedback (`POST /api/v1/feedback`)
Records user thumbs-up / thumbs-down evaluation and optional comments for answer quality tracking and governance audits.

* **Required Role:** Authenticated (`admin`, `editor`, `viewer`)

```bash
curl -X POST "http://localhost:8000/api/v1/feedback" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "How does the hardware replacement approval process work?",
       "feedback": "positive",
       "comment": "Accurate response with exact runbook references.",
       "agent": "doc_agent"
     }'
```

* `agent` *(optional)*: the rated answer's `active_agent` (lowercase letters, digits, underscores); it counts in `GET /api/v1/admin/agent-stats`.

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Feedback recorded."
}
```

---

## 🗄️ 4. Enterprise Database Endpoints

### 4.1 Database Status & Schema (`GET /api/v1/database/status`)
Returns database connection status, dialect type, accessible tables (filtered by `DB_ALLOWED_TABLES`), and the schema summary that is also given to `db_agent`.

```bash
curl -X GET "http://localhost:8000/api/v1/database/status" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "connection": {
    "status": "connected",
    "message": "Successfully connected (SQLITE).",
    "dialect": "sqlite",
    "tables": ["destek_talepleri", "satislar", "urunler"],
    "table_count": 3
  },
  "schema_summary": "# DATABASE SCHEMA (Dialect: SQLITE)\nTable: destek_talepleri\n  Columns: talep_id (INTEGER [PK]), talep_kodu (TEXT), musteri_adi (TEXT), konu (TEXT), detay (TEXT), cozum (TEXT), durum (TEXT)\n..."
}
```

---

### 4.2 Safe Read-Only Query (`POST /api/v1/database/test-query`)
Executes an ad-hoc read-only query against the connected database. Only a single `SELECT` / `WITH` statement is accepted; modifying keywords, dangerous functions, and tables outside `DB_ALLOWED_TABLES` are rejected (see [Database Connectors](database_connectors.md#-strict-read-only-security-guard)).

* **Required Role:** `admin`

```bash
curl -X POST "http://localhost:8000/api/v1/database/test-query" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "SELECT urun_adi, stok_adedi FROM urunler WHERE stok_adedi < 20"
     }'
```

**Example Response:**
```json
{
  "status": "success",
  "data": {
    "status": "success",
    "columns": ["urun_adi", "stok_adedi"],
    "rows": [
      {"urun_adi": "NovaTech Enterprise Server X1", "stok_adedi": 14},
      {"urun_adi": "NovaShield Enterprise Firewall", "stok_adedi": 8}
    ],
    "row_count": 2,
    "query": "SELECT urun_adi, stok_adedi FROM urunler WHERE stok_adedi < 20"
  }
}
```

**Rejected Query (HTTP 400):**
```json
{
  "detail": "Security Guard: Forbidden keyword 'DELETE' detected. Only read-only (SELECT) queries are allowed."
}
```

---

### 4.3 Table ETL Vectorization (`POST /api/v1/database/sync-table`)
Converts relational database rows into contextual text chunks and indexes them into ChromaDB for dense retrieval. Re-syncing a table first removes all of its previously indexed rows, so deleted rows do not linger in the index.

* **Required Role:** `admin`
* **Body:** `table_name` (required), `text_columns` (optional, default: all columns), `title_column` (optional, added to each chunk header), `id_column` (optional, auto-detected otherwise).

```bash
curl -X POST "http://localhost:8000/api/v1/database/sync-table" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "table_name": "destek_talepleri",
       "text_columns": ["konu", "detay", "cozum"],
       "title_column": "konu",
       "id_column": "talep_id"
     }'
```

**Example Response:**
```json
{
  "status": "success",
  "message": "Table 'destek_talepleri' indexed successfully (3 chunks).",
  "table_name": "destek_talepleri",
  "chunk_count": 3
}
```

---

## 📜 5. Compliance & Admin Audit Endpoints

### 5.1 Audit Logs (`GET /api/v1/admin/audit-logs`)
Retrieves compliance audit logs with filtering across user, action, status, and date range.

* **Required Role:** `admin`
* **Query Parameters:**
  * `username` *(optional)*: Filter by username (e.g. `admin`).
  * `action` *(optional)*: Filter by action (`query`, `query_stream`, `feedback`, `upload`, `delete`, `login`, `token_refresh`, `change_password`, `register_user`, `update_user`, `delete_user`, `db_query`, `db_sync_table`, `session_cleanup`, `backup_create`, `backup_restore`, `audit_verify`).
  * `status` *(optional)*: Filter by result status (`success`, `error`, `denied`, `warning`, `cancelled`).
  * `start_date` / `end_date` *(optional)*: ISO timestamps.
  * `limit` *(int, default 50)*: Number of logs to retrieve (1-200).
  * `offset` *(int, default 0)*: Offset for pagination.

```bash
curl -X GET "http://localhost:8000/api/v1/admin/audit-logs?action=query&status=success&limit=25" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "total": 120,
  "count": 25,
  "limit": 25,
  "offset": 0,
  "logs": [
    {
      "id": 1,
      "timestamp": "2026-09-18T10:30:15.120000+00:00",
      "username": "jane_analyst",
      "user_role": "editor",
      "action": "query",
      "detail": "[doc_agent] What is the password update policy?",
      "sources_used": ["NovaTech_Security_Policy.pdf"],
      "answer_preview": "User passwords must be updated at least every 90 days...",
      "ip_address": "192.168.1.50",
      "duration_ms": 342,
      "status": "success",
      "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "entry_hash": "f45d1942d04610d03838bcf3c49b77648012efb34817cbe5f7e3797fdee5e61e"
    }
  ]
}
```

---

### 5.2 Audit Statistics (`GET /api/v1/admin/audit-stats`)
Returns aggregated governance metrics: total audit records, queries executed, files uploaded, files deleted, logins, and errors.

* **Required Role:** `admin`

```bash
curl -X GET "http://localhost:8000/api/v1/admin/audit-stats" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "total_records": 150,
  "queries_executed": 112,
  "stream_queries_executed": 45,
  "documents_uploaded": 8,
  "documents_deleted": 2,
  "login_events": 24,
  "error_events": 4,
  "feedback_events": 18
}
```

---

### 5.2a Verify Audit Trail Integrity (`GET /api/v1/admin/audit-verify`)
Recomputes the SHA-256 hash chain over all audit entries. Editing or deleting a past entry is reported via `first_invalid_id`. Store `head_hash` outside the server; if a later verification no longer builds on it, the log was truncated or rewritten.

```json
{
  "status": "success",
  "valid": true,
  "checked_entries": 1284,
  "unverifiable_legacy_entries": 0,
  "first_invalid_id": null,
  "head_hash": "3f5c...e91a",
  "purged_before": "2026-03-01T00:00:00+00:00"
}
```

`purged_before` is set when the retention policy (`AUDIT_RETENTION_DAYS`) has deleted older entries; verification then starts from the hash of the newest deleted entry, so the remaining chain is still checked end to end.

---

### 5.3 Session Cleanup (`POST /api/v1/admin/cleanup-sessions`)
Deletes multi-agent conversation threads whose most recent activity is older than the specified retention window.

* **Required Role:** `admin`
* **Query Parameters:**
  * `max_age_days` *(int, optional, default: 30, range: 1-365)*: Maximum session age in days before pruning.

```bash
curl -X POST "http://localhost:8000/api/v1/admin/cleanup-sessions?max_age_days=14" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Removed 12 expired conversation session(s).",
  "deleted_sessions": 12
}
```

---

### 5.4 Create Full Backup (`POST /api/v1/admin/backup`)
Creates `backups/full_backup_<timestamp>/` with `vector_db/` (the search index, copied while index writes are paused) and `data/` (documents, `users.json`, audit log, conversation memory, sample database). SQLite databases are copied with the SQLite backup API, so the snapshot is consistent while the server is running. The JWT signing secret is not included. Restoring `data/` requires stopping the server (see [Docker Deployment](docker_deployment.md#-backups--restore)).

* **Required Role:** `admin`

```bash
curl -X POST "http://localhost:8000/api/v1/admin/backup" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Full backup created (vector index, documents, users, audit log, conversations).",
  "backup_path": "backups/full_backup_20260925_220000"
}
```

---

### 5.5 List Backups (`GET /api/v1/admin/backups`)
Lists full backups (`type: "full"`) and vector-index-only backups from earlier versions (`type: "vector_db"`), newest first.

* **Required Role:** `admin`

```bash
curl -X GET "http://localhost:8000/api/v1/admin/backups" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "count": 2,
  "backups": [
    {
      "name": "full_backup_20260925_220000",
      "type": "full",
      "path": "backups/full_backup_20260925_220000",
      "created_at": "2026-09-25T22:00:00+00:00"
    },
    {
      "name": "vector_db_backup_20260924_180000",
      "type": "vector_db",
      "path": "backups/vector_db_backup_20260924_180000",
      "created_at": "2026-09-24T18:00:00+00:00"
    }
  ]
}
```

---

### 5.6 Restore Vector Index (`POST /api/v1/admin/restore`)
Stages a restore of the vector index from a backup (for a full backup, its `vector_db/` part). Users, the audit log, conversations, and documents are not changed; restore those by following the [full restore procedure](docker_deployment.md#-backups--restore). The live database is never modified while the server has it open: the swap is applied on the next server start.

> [!CAUTION]
> After the restart, the restored snapshot completely replaces the active vector database. The replaced database is preserved as `backups/pre_restore_<timestamp>`.

* **Required Role:** `admin`
* **Query Parameters:**
  * `backup_name` *(string, required)*: Directory name of the backup to restore (from `/api/v1/admin/backups`).

```bash
curl -X POST "http://localhost:8000/api/v1/admin/restore?backup_name=full_backup_20260925_220000" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Restore from 'full_backup_20260925_220000' staged. Restart the server to apply it."
}
```

---

### 5.7 Run Maintenance Now (`POST /api/v1/admin/maintenance/run`)
Applies `AUDIT_RETENTION_DAYS` and `SESSION_RETENTION_DAYS` and creates a full backup if `BACKUP_INTERVAL_HOURS` is set and the last full backup is older than that (then prunes to `BACKUP_KEEP`). The same job runs automatically at startup and every hour; with all settings at their defaults it does nothing. See [Data Protection](data_protection.md).

* **Required Role:** `admin`

```bash
curl -X POST "http://localhost:8000/api/v1/admin/maintenance/run" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "results": {
    "audit_entries_deleted": 312,
    "sessions_deleted": 4,
    "backup_path": "backups/full_backup_20260927_030000",
    "backups_pruned": 1
  }
}
```

---

### 5.7a Answers to Review (`GET /api/v1/admin/review`)
Recent answers whose check ended `partial` or `unverified`, including questions the documents did not answer (audit entries of `query` / `query_stream` with status `warning`), and feedback entries rated down, newest first (`limit`, default 30). Admins and editors. Each item is an audit entry plus `reason` (`unverified` or `negative_feedback`) and `question` (the question text, `""` with `AUDIT_STORE_QUESTIONS=false`, where only its length is stored). Questions answered in the FAQ are left out.

### 5.7b Staff Answers (FAQ) (`/api/v1/admin/faq`, `/api/v1/faq/answers`)
Staff answer the questions of the review list; the assistant uses the answers for later questions and the users who asked are told. Admins and editors:

* `POST /api/v1/admin/faq` with `{"question": "...", "answer": "...", "groups": []}` stores the answer in `data/faq.json` (part of full backups) and indexes it as a chunk of the source *"SSS (personel cevapları)"*, visible like a document with these `groups` (empty: everyone). Every user in the review list who asked the same question (same words, ignoring case and spacing) is recorded in `asked`; their questions leave the review list. Response: `{"entry": {"id", "question", "answer", "groups", "author", "created_at", "updated_at", "asked": [{"username", "question"}], "seen_by": []}}`.
* `GET /api/v1/admin/faq` lists the answers (`entries`); `PUT /api/v1/admin/faq/{entry_id}` changes one (a changed answer is shown to the askers again); `DELETE` removes it from the store and the index.

Users with an account (not guests): `GET /api/v1/faq/answers` returns `{"answers": [{"id", "question", "answer", "updated_at"}]}` for their questions they have not marked as seen; `POST /api/v1/faq/answers/seen` with `{"ids": ["..."]}` marks them. The web UI shows them under the bell in the header.

### 5.7c Agent Performance (`GET /api/v1/admin/agent-stats`)
Per agent over the last `days` days (1-365, default 30), from the audit log: `questions`, `median_ms` and `p90_ms` (answer time), `warnings` and `warning_rate` (answers that could not be fully verified or found), `errors` and `error_rate`, and the users' `positive` / `negative` ratings (feedback sent with `agent`). Failed questions recorded before an agent was chosen count as `unknown`. Admin only.

### 5.7d Web UI Texts (`/api/v1/ui-settings`, `/api/v1/admin/ui-settings`)
What differs by organization in the web UI. `GET /api/v1/ui-settings` needs no login (the login page shows the name):

```json
{
  "app_name": "AtaRehber",
  "default_language": "tr",
  "texts": {
    "tr": {"welcome": "", "welcome_guest": "", "disclaimer": "", "request_example": "", "unit_label": "Fakülte",
           "program_label": "", "level_label": "", "suggestions": ["Burs başvurusu ne zaman?"]},
    "en": {"...": "..."}
  }
}
```

An empty text means the web UI's built-in one. `default_language` is `UI_LANGUAGE` (for users who did not pick a language), and `UI_DISCLAIMER` fills an empty `disclaimer`. Admins read the stored values (with `updated_by`, `updated_at`) with `GET /api/v1/admin/ui-settings` and replace them with `PUT` and the same body without `default_language`: `app_name` up to 40 characters, `welcome`, `welcome_guest`, and `disclaimer` up to 300, `request_example` up to 150, the three profile field labels up to 60, and up to 6 `suggestions` of 150 characters. Texts are stored on one line in `data/ui_settings.json` (part of full backups); the change is audited as `ui_settings`.

### 5.8 Custom Agents (`/api/v1/admin/custom-agents`)
Agents defined without code (see [Custom Agents Guide](custom_agents_guide.md#-agents-without-code-web-ui)). `PUT /api/v1/admin/custom-agents/{name}` takes:

```json
{
  "name": "not_asistani",
  "display_name": "Not Asistanı",
  "description": "Not ortalaması, harf notu ve AGNO hesaplama soruları",
  "instructions": "Vize ve final notlarından yönetmeliğe göre ortalamayı hesapla ve harf notunu açıkla.",
  "tools": ["documents", "calculator"],
  "enabled": true
}
```

* `name` must match the path; 3-40 lowercase letters, digits, underscores; built-in agent names are rejected (HTTP 400).
* `tools`: any of `documents`, `calculator`, `dates`, `database` (`GET /api/v1/admin/agent-tools` lists them). Unknown tools or too short texts: HTTP 422.
* The response contains the stored record with `created_by`, `created_at`, `updated_by`, `updated_at`. `GET` lists them with `available` (enabled, and at least one of its tools works if it has tools).

---

## 📝 5b. Service Request Endpoints

Requests are filed through the chat (`request_agent`, after the user confirms the draft) or with the form endpoint below, and stored in `data/requests.db`. Statuses: `open`, `in_progress`, `resolved`, `rejected`, `cancelled`. If `SMTP_HOST` and `REQUEST_NOTIFY_EMAILS` are configured, the unit responsible for the category is e-mailed. All changes are audited (`request_create`, `request_update`).

### 5b.1 List Requests (`GET /api/v1/requests`)
* **Query parameters:** `status` (optional filter), `all_users` (staff only: everyone's requests), `limit` (1-500, default 50).
* Viewers always get their own requests. The response also contains the configured `categories`.

```bash
curl "http://localhost:8000/api/v1/requests?all_users=true&status=open" -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "status": "success",
  "count": 1,
  "requests": [
    {"id": 12, "created_at": "2026-09-27T10:02:11+00:00", "updated_at": "2026-09-27T10:02:11+00:00", "username": "ayse",
     "category": "it_support", "title": "B204 projektör çalışmıyor", "description": "…", "status": "open",
     "resolution_note": "", "updated_by": null, "notified": true}
  ],
  "categories": ["it_support", "facilities", "academic", "administrative", "other"]
}
```

### 5b.2 File a Request (`POST /api/v1/requests`)
* **Body:** `category` (mapped onto `REQUEST_CATEGORIES`; unknown values become `other`), `title` (3-200 characters), `description` (optional). Returns HTTP 201 with the stored request.

```bash
curl -X POST "http://localhost:8000/api/v1/requests" -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"category": "facilities", "title": "Klima çalışmıyor", "description": "A blok 3. kat toplantı odası"}'
```

### 5b.3 Update a Request (`PATCH /api/v1/requests/{request_id}`)
* **Body:** `status` and optional `resolution_note`.
* `admin` and `editor` can set any status. Requesters can only set `cancelled` on their own `open` or `in_progress` request (HTTP 403 otherwise); other users' requests return HTTP 404.

```bash
curl -X PATCH "http://localhost:8000/api/v1/requests/12" -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"status": "resolved", "resolution_note": "Projektör lambası değiştirildi."}'
```

---

## 🛡️ 6. Rate Limiting & Protection

The API implements an in-memory sliding-window rate limiter to safeguard on-premise hardware against abuse and resource exhaustion:

* **Scope:** Authenticated requests are limited per account; anonymous requests per client IP. Users sharing a gateway (such as a UI container) therefore do not share one budget. Calls without a bearer token, such as login and the web UI's cookie-based token refresh, are counted per IP, so behind a proxy the backend must see the real client IP (`FORWARDED_ALLOW_IPS`, set by the HTTPS compose).
* **Configuration:** `RATE_LIMIT_PER_MINUTE` (default `30`) limits questions, uploads, and other changes (`POST`, `PUT`, `PATCH`, `DELETE`); reads (`GET`) have their own budget, `RATE_LIMIT_READS_PER_MINUTE` (default `300`), because the web UI reloads its panels with several `GET` requests on every click.
* **Bypassed Routes:** `/health` and documentation endpoints (`/docs`, `/redoc`, `/openapi.json`) are excluded.
* **Login brute-force protection:** handled separately by per-account lockout (see section 1.1).
* **HTTP 429 Too Many Requests:** When a client exceeds the limit, the API immediately returns HTTP 429:

```json
{
  "detail": "Rate limit exceeded. Maximum 30 requests per minute.",
  "retry_after": 60
}
```

* **Header:** Includes `Retry-After: 60` indicating the number of seconds until the sliding window clears.

---

## 🔒 7. CORS Configuration

CORS origins are configured via the `CORS_ORIGINS` environment variable in `.env`:

```env
# Comma-separated list of allowed web origins
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
```

Credentials (`allow_credentials=True`), all methods, and all headers are permitted for these trusted origins.
