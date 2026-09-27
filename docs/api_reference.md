# 🔌 REST API Documentation

`OpenLocalRagAgents` exposes a high-performance REST API built on **FastAPI** to enable turnkey integration with enterprise portals, CRM, ERP, and internal workplace bots.

The interactive OpenAPI Swagger UI is available at `http://localhost:8000/docs` whenever the server is running.

---

## 📋 Endpoints Overview

| Method | Endpoint | Required Role | Description |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/auth/login` | Public | Obtain signed JWT Bearer access token and refresh token |
| `POST` | `/api/v1/auth/refresh` | Public | Exchange refresh token for fresh access and refresh token pair |
| `GET` | `/api/v1/auth/me` | Authenticated | View current authenticated user profile |
| `POST` | `/api/v1/auth/register` | `admin` | Register new user account with password policy enforcement |
| `GET` | `/api/v1/auth/users` | `admin` | List all registered enterprise user accounts |
| `PATCH` | `/api/v1/auth/users/{username}` | `admin` | Update user status (disable/enable), role, or reset password |
| `DELETE` | `/api/v1/auth/users/{username}` | `admin` | Permanently delete a registered user account |
| `GET` | `/api/v1/stats` | Authenticated | Hardware acceleration, active models, backend info, and index counts |
| `GET` | `/api/v1/documents` | Authenticated | List uploaded and indexed enterprise documents with chunk stats |
| `POST` | `/api/v1/upload-file` | `admin`, `editor` | Upload new PDF, DOCX, or TXT document and auto-index into ChromaDB |
| `DELETE` | `/api/v1/documents/{filename}` | `admin`, `editor` | Permanently delete document from disk and purge chunks from vector store |
| `GET` | `/api/v1/agents` | Authenticated | List the supervisor (`auto`) and all registered specialist sub-agents |
| `POST` | `/api/v1/query` | Authenticated | Multi-agent question answering with multi-turn session memory |
| `POST` | `/api/v1/query-stream` | Authenticated | Same workflow as `/query`, streamed as NDJSON events |
| `POST` | `/api/v1/feedback` | Authenticated | Submit thumbs-up/down evaluation on agent answers |
| `GET` | `/api/v1/database/status` | Authenticated | Database connection status, dialect type, and schema summary |
| `POST` | `/api/v1/database/test-query` | `admin` | Execute safe read-only SELECT queries |
| `POST` | `/api/v1/database/sync-table` | `admin` | Convert database table rows into ChromaDB vector chunks |
| `GET` | `/api/v1/admin/audit-logs` | `admin` | Filter and inspect compliance audit trail logs |
| `GET` | `/api/v1/admin/audit-stats` | `admin` | Metrics summary (queries, uploads, logins, errors, feedback) |
| `GET` | `/api/v1/admin/audit-verify` | `admin` | Verify the audit trail hash chain and return its head hash |
| `POST` | `/api/v1/admin/cleanup-sessions`| `admin` | Prune conversation sessions older than specified age |
| `POST` | `/api/v1/admin/backup` | `admin` | Create timestamped ChromaDB vector database snapshot |
| `GET` | `/api/v1/admin/backups` | `admin` | List available ChromaDB backup snapshots |
| `POST` | `/api/v1/admin/restore` | `admin` | Stage a ChromaDB restore from a snapshot (applied on next restart) |
| `POST` | `/api/v1/auth/change-password` | Authenticated | Change own password (required after first login with the default password) |
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
  "must_change_password": false
}
```

---

### 1.4 Register User (`POST /api/v1/auth/register`)
Registers a new enterprise user. Restricted to `admin` role.

* **Roles Available:** `admin`, `editor`, `viewer`
* **Password Policy:** Passwords must meet configurable enterprise security rules (minimum 8 characters, uppercase, lowercase, and digit required by default). Violations return HTTP 400 with the list of unmet rules.

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "username": "jane_analyst",
       "password": "SecurePassword123!",
       "role": "editor"
     }'
```

**Example Response (HTTP 201):**
```json
{
  "username": "jane_analyst",
  "role": "editor",
  "disabled": false,
  "created_at": "2026-09-18T11:20:00"
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
Modifies a user's role, status (enable/disable), or resets their password. Restricted to `admin` role.

* New passwords are validated against the password policy (HTTP 400 on violation).
* Resetting the password or disabling the account revokes all of the user's existing tokens.

```bash
curl -X PATCH "http://localhost:8000/api/v1/auth/users/jane_analyst" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{
       "role": "admin",
       "disabled": false
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
Returns the embedding and LLM models, whether Ollama is ready (`llm_status`: `"ok"` or a problem with the fix, e.g. `"... Run: ollama pull qwen2.5:7b"`), the retrieval device, and vector collection statistics.

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
Returns file metadata and vector chunk counts for all uploaded files in `data/`.

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
      "modified_at": "2026-09-18 10:15:22"
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

```bash
curl -X POST "http://localhost:8000/api/v1/upload-file" \
     -H "Authorization: Bearer <token>" \
     -F "file=@NovaTech_Security_Policy.pdf"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "'NovaTech_Security_Policy.pdf' successfully uploaded and indexed.",
  "filename": "NovaTech_Security_Policy.pdf",
  "chunk_count": 14
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

---

## 🤖 3. AI Query Endpoints

### 3.0 List Agents (`GET /api/v1/agents`)
Returns the routing options for the `agent` query parameter: `auto` (supervisor routing) plus every registered specialist.

```bash
curl -X GET "http://localhost:8000/api/v1/agents" \
     -H "Authorization: Bearer <token>"
```

**Example Response:**
```json
{
  "agents": [
    {"name": "auto", "display_name": "👑 Auto (Supervisor Orchestrator)", "description": "Automatically analyzes question intent and delegates to the best specialist sub-agent or responds directly.", "version": "2.0.0"},
    {"name": "doc_agent", "display_name": "Document & Policy RAG Specialist", "description": "Answers questions about what company documents say: policies, procedures, ...", "version": "1.0.0"},
    {"name": "db_agent", "display_name": "SQL & Database Analyst", "description": "Used for querying structured relational database tables ...", "version": "1.0.0"},
    {"name": "compliance_agent", "display_name": "Enterprise Compliance Auditor", "description": "Gives a formal verdict [COMPLIANT / WARNING / VIOLATION] on a specific action ...", "version": "1.0.0"}
  ]
}
```

---

### 3.1 Batch Query (`POST /api/v1/query`)
Runs the multi-agent LangGraph workflow: the supervisor routes the question to a specialist (or answers greetings directly), the specialist produces the answer, and the turn is saved to the session history. See [Architecture](architecture.md#-multi-agent-workflow-srcagentmulti_agent) for details.

* **Request Parameters:**
  * `question` *(string, required)*: The user question (1-4000 characters).
  * `session_id` *(string, optional)*: Up to 64 characters of `[a-zA-Z0-9_-]`. Turns with the same `session_id` share conversation memory, stored per user in `data/multi_agent_conversations.db`. Without it, the query is single-turn and nothing is persisted.
  * `agent` *(string, optional)*: `auto` (default) for supervisor routing, or a registered agent name from `GET /api/v1/agents` (e.g. `doc_agent`, `db_agent`, `compliance_agent`) to bypass routing. Unknown names fall back to supervisor routing.

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
      "distance": 0.421,
      "reranker_score": 0.9871
    }
  ],
  "active_agent": "doc_agent",
  "agent_trace": [
    {"agent": "supervisor", "action": "intent_routing", "target_agent": "doc_agent", "reason": "Question about company policy", "duration_ms": 612, "status": "success", "timestamp": "2026-09-18T10:30:14+00:00"},
    {"agent": "doc_agent", "action": "retrieval_and_generation", "search_query": "workstation password rotation policy", "sources_count": 3, "hallucination_grade": "yes", "is_refined": false, "duration_ms": 2710, "status": "success", "timestamp": "2026-09-18T10:30:17+00:00"}
  ],
  "hallucination_grade": "yes",
  "is_refined": false
}
```

* **`active_agent`:** the agent that produced the answer (`supervisor` for direct answers).
* **`sources[].reranker_score`:** cross-encoder relevance from 0 to 1. Chunks below `RAG_MIN_RERANKER_SCORE` (default `0.005`) are never used or returned.
* **Response language:** answers follow the language of the question (Turkish or English; other languages on a best-effort basis with English fixed texts, see [Language Support](language_support.md)); a question without language cues, such as a bare ticket code, inherits the language of the session's earlier questions. The fixed texts below are shown in English; Turkish questions get the Turkish versions (e.g. *"Bu bilgi şirket dokümanlarında bulunmuyor."*). Compliance verdict labels such as `[VIOLATION / PROHIBITED]` stay in English in both languages.
* **No relevant documents:** if no chunk passes the relevance gate, `doc_agent` answers *"This information is not found in company documents."* with empty `sources`, and `compliance_agent` returns an `[UNDETERMINED]` verdict. The LLM is not called in either case.
* **`hallucination_grade` / `is_refined`:** set by `doc_agent`'s Self-RAG guard. An unverifiable answer is replaced by *"This information cannot be fully verified against company documents."* Other agents leave `hallucination_grade` empty.
* **`db_agent` traces** include the executed `sql` and `row_count`.
* **LLM unavailable:** if Ollama cannot be reached, the request still returns HTTP 200 with a fallback answer (for `doc_agent` the same *"cannot be fully verified"* text). Check `llm_status` in `GET /api/v1/stats` when answers suddenly degrade.

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
{"type": "agent_selected", "agent": "doc_agent", "display_name": "Document & Policy RAG Specialist", "reason": "Task delegated to specialist: 'Document & Policy RAG Specialist'."}
{"type": "status", "message": "🤖 Document & Policy RAG Specialist: Executing specialized task...", "node": "doc_agent"}
{"type": "sources", "sources": [{"source": "IT_Support_Runbook.docx", "chunk_index": 1, "...": "..."}]}
{"type": "done", "answer": "...", "sources": [], "agent_trace": [], "active_agent": "doc_agent", "hallucination_grade": "yes", "is_refined": false}
```

* For greetings answered by the supervisor, `agent_selected` has `"agent": "supervisor"` and no `sources` event is sent.
* On failure, an `{"type": "error", "message": "An internal error occurred while processing the query."}` event is sent before the stream ends.
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
       "comment": "Accurate response with exact runbook references."
     }'
```

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
  "head_hash": "3f5c...e91a"
}
```

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

### 5.4 Create Vector Database Backup (`POST /api/v1/admin/backup`)
Creates a timestamped snapshot of the ChromaDB vector database directory. Index writes are paused while copying.

* **Required Role:** `admin`

```bash
curl -X POST "http://localhost:8000/api/v1/admin/backup" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Vector database backup created successfully.",
  "backup_path": "backups/vector_db_backup_20260925_220000"
}
```

---

### 5.5 List Vector Database Backups (`GET /api/v1/admin/backups`)
Lists all available ChromaDB backup snapshot archives with timestamp and size metadata.

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
      "name": "vector_db_backup_20260925_220000",
      "path": "backups/vector_db_backup_20260925_220000",
      "created_at": "2026-09-25T22:00:00+00:00"
    },
    {
      "name": "vector_db_backup_20260924_180000",
      "path": "backups/vector_db_backup_20260924_180000",
      "created_at": "2026-09-24T18:00:00+00:00"
    }
  ]
}
```

---

### 5.6 Restore Vector Database (`POST /api/v1/admin/restore`)
Stages a restore of the ChromaDB vector database from an existing named snapshot. The live database is never modified while the server has it open: the swap is applied on the next server start.

> [!CAUTION]
> After the restart, the restored snapshot completely replaces the active vector database. The replaced database is preserved as `backups/pre_restore_<timestamp>`.

* **Required Role:** `admin`
* **Query Parameters:**
  * `backup_name` *(string, required)*: Directory name of the backup to restore (from `/api/v1/admin/backups`).

```bash
curl -X POST "http://localhost:8000/api/v1/admin/restore?backup_name=vector_db_backup_20260925_220000" \
     -H "Authorization: Bearer <admin_token>"
```

**Example Response (HTTP 200):**
```json
{
  "status": "success",
  "message": "Restore from 'vector_db_backup_20260925_220000' staged. Restart the server to apply it."
}
```

---

## 🛡️ 6. Rate Limiting & Protection

The API implements an in-memory sliding-window rate limiter to safeguard on-premise hardware against abuse and resource exhaustion:

* **Scope:** Authenticated requests are limited per account; anonymous requests per client IP. Users sharing a gateway (such as the Streamlit frontend container) therefore do not share one budget.
* **Configuration:** Configured via `RATE_LIMIT_PER_MINUTE` in `.env` (default: `30` requests/minute).
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
CORS_ORIGINS=http://localhost:8501,http://127.0.0.1:8501
```

Credentials (`allow_credentials=True`), all methods, and all headers are permitted for these trusted origins.
