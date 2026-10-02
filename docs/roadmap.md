# 🗺️ Project Roadmap

The strategic development roadmap for `AtaRehber` is structured below to expand its capabilities as a world-class on-premise enterprise AI infrastructure.

---

## 🚨 Phase 0 — Critical Bug Fixes & Security Hardening ✅

> **Status: COMPLETED** — All critical issues resolved.

- [x] **JWT Secret Key Management Hardening:**
  - Added `.jwt_secret` to `.gitignore` to prevent accidental secret key exposure in version control.
  - Documented mandatory `.env` configuration for production deployments via `.env.example`.
- [x] **User Store Thread Safety Fix:**
  - Replaced `threading.Lock` with `threading.RLock` in `UserStore` to prevent deadlocks from nested `get_user()` calls within `authenticate_user()`.
- [x] **Core `__init__.py` Export Fix:**
  - Added missing `SAMPLE_DB_PATH` import in `src/core/__init__.py` to resolve potential `ImportError` at runtime.
- [x] **Stream Endpoint Audit Logging:**
  - Implemented full audit trail logging for `/api/v1/query-stream` endpoint with answer capture and duration tracking.
- [x] **SQLite Connection Lifecycle Management:**
  - Implemented proper connection cleanup for the LangGraph `SqliteSaver` checkpointer via `agent.cleanup()`.
  - Added graceful shutdown hooks in FastAPI lifespan via `cleanup_services()`.
- [x] **`.env.example` Template:**
  - Created comprehensive `.env.example` documenting all environment variables with safe defaults and inline comments.

---

## 🔍 Phase 1 — Advanced Retrieval & Structured Ingestion

- [x] **Retrieval & Answer Quality Evaluation:**
  - Labeled question set and harness (`python -m evals.run_eval`) measuring retrieval hit rate/MRR, off-topic rejection, similarity and reranker threshold sweeps, supervisor routing accuracy, and end-to-end answer accuracy with before/after comparison. See the [Evaluation Guide](evaluation.md).
- [ ] **Stored-Value Hints for Text-to-SQL:**
  - Show sample values of low-cardinality columns (statuses, categories) in the SQL prompt so generated filters match what is stored. Evaluation case `db-04` filters on `'çözüldü'` while the table stores `'Resolved'`.
- [ ] **Hybrid Search (BM25 + Dense Vector with Reciprocal Rank Fusion):**
  - Merge semantic dense vector search with sparse keyword/code matching (BM25) via *Reciprocal Rank Fusion (RRF)* to achieve 100% precision on SKU codes and technical terminology.
- [ ] **Complex Table & Unstructured Document Parsing:**
  - Dedicated table segmentation and layout-aware chunking for Excel (`.xlsx`), CSV, and complex multi-column PDF reports.
- [ ] **Hierarchical & Parent-Child Chunking:**
  - Multi-tier indexing that performs granular vector search on small child chunks while providing parent contextual blocks to the LLM during generation.
- [ ] **Graph-Augmented RAG (GraphRAG):**
  - Transform enterprise entities and document relations into Knowledge Graphs for multi-hop causal reasoning and cross-departmental impact analysis.
- [x] **Configurable Chunking Parameters:**
  - Exposed `CHUNK_SIZE` and `CHUNK_OVERLAP` as environment variables instead of hardcoded values in `DocumentLoader`.
- [ ] **Document Versioning & History:**
  - Track document upload/re-upload history with version timestamps and diff metadata.
  - Allow admins to rollback to previous document versions.

---

## 🤖 Phase 2 — Next-Gen Agentic RAG

- [x] **Multi-Turn Conversational Memory (LangGraph Checkpointer):**
  - LangGraph SQLite checkpointer (`multi_agent_conversations.db`) with per-user session threads (`{username}_{session_id}`).
  - Supervisor routing, document query rewriting, and SQL generation all use the recent conversation turns.
- [x] **Dynamic Query Rewriting & Expansion:**
  - Autonomous `rewrite` node in LangGraph that rewrites ambiguous user prompts into optimized search representations before querying the vector store.
  - Resolves pronouns and references using conversation history for multi-turn coherence.
- [x] **Closed-Loop Self-Correction & Refinement:**
  - Integrated `refine` node in LangGraph routed back to `grade` to audit refined responses, ensuring high factual fidelity.
- [x] **Universal Relational Database Connector & Text-to-SQL Tools:**
  - SQLAlchemy-based connector layer supporting PostgreSQL, MSSQL, MySQL, Oracle, and SQLite.
  - Token-level read-only query guardrails, database-enforced read-only sessions, row capping (`DB_MAX_ROWS`), and table allowlisting.
  - Table-to-vector ETL pipeline (`DatabaseTableLoader`).
- [x] **Multi-Agent Supervisor Teams:**
  - Supervisor pattern routing queries dynamically across specialized agents (`doc_agent`, `db_agent`, `compliance_agent`) with a pluggable registry for custom agents.
- [x] **Answers in the User's Language:**
  - Turkish and English: language detection, prompts that name the target language, localized fixed texts and compliance report headings, `language_match_rate` in the evaluation (63% → 100%).
- [ ] **Additional Response Languages (Mandarin Chinese, Hindi, Spanish):**
  - The three most spoken languages after English. Spanish already answers correctly on a best-effort basis; Chinese and Hindi answers currently fail the Self-RAG check. See [Language Support](language_support.md#-coming-soon).
- [ ] **Additional Specialist Agents:**
  - Code Analysis Agent and multi-agent collaboration (one question answered by several specialists in sequence).
- [x] **User Feedback Loop:**
  - Thumbs up/down feedback buttons in Streamlit UI with `/api/v1/feedback` API endpoint.
  - Feedback events recorded in the compliance audit trail for answer quality tracking.
- [x] **Conversation Session Management:**
  - Admin endpoint `/api/v1/admin/cleanup-sessions` for TTL-based cleanup of expired sessions.
- [x] **SQL Injection Guard Enhancement:**
  - Token-level `sqlparse` analysis (single statement, forbidden keywords and functions, table allowlist across joins, subqueries and CTEs) plus database-enforced read-only sessions.

---

## ⚡ Phase 3 — Serving Optimization & Inference Acceleration

- [x] **Request Serialization & Concurrency Protection:**
  - `QueryConcurrencyManager` caps concurrent LLM requests to Ollama with `asyncio.Semaphore(OLLAMA_NUM_PARALLEL)`.
- [x] **Optimized Inference Engine Integration (Ollama / vLLM):**
  - The LLM is served exclusively by Ollama (`langchain-ollama`); the in-process HuggingFace backend was removed. 7B/14B models (`qwen2.5:7b`, `llama3.1:8b`) and parallel requests, with a startup availability check.
  - `ollama` service with automatic first-start model pull in `docker-compose.yml`; the GPU override assigns the GPU to Ollama.
- [ ] **Semantic Vector Caching:**
  - Cache recurring queries using vector similarity (Redis / GPTCache) to answer repeated enterprise questions with near-zero latency.
- [ ] **Speculative Decoding:**
  - Accelerate local LLM token generation using small draft models.
- [x] **API Rate Limiting:**
  - Sliding-window rate limiting per authenticated account (per IP for anonymous requests) with configurable `RATE_LIMIT_PER_MINUTE`.
  - Returns `429 Too Many Requests` with `Retry-After` header.
- [ ] **WebSocket Streaming Support:**
  - Replace NDJSON-based streaming with WebSocket connections for lower-latency, bidirectional real-time communication.

---

## 🏢 Phase 4 — Enterprise Security, Governance & DevOps

- [x] **Automated Testing Suite:**
  - Unit, end-to-end (real LangGraph workflow with stubbed LLM), and security tests covering routing and memory, Self-RAG, SQL guard bypass attempts, file upload security, authentication/RBAC and token revocation, rate limiting, audit hash chain, backup/restore, and resource stability.
- [x] **Defense-in-Depth API Security:**
  - Path traversal protection, file extension whitelisting, upload size limits, and configurable CORS origins.
- [x] **Centralized Logging & Lifespan Architecture:**
  - Standardized logger with console and rotating file handlers (`src.core.logger`), `.env` support, and FastAPI lifespan model loading.
- [x] **Role-Based Access Control (RBAC) & JWT Authentication:**
  - Native JWT Bearer token generation, bcrypt password hashing, and user role enforcement (`admin`, `editor`, `viewer`).
  - Permission-gated endpoints for document management, database queries, and user administration.
- [x] **Enterprise Audit Trail & Compliance Logging:**
  - Structured SQLite audit database (`data/audit.db`) recording all queries, file uploads/deletions, logins, and anomalies with execution duration and client IP.
  - SHA-256 hash chain with `/api/v1/admin/audit-verify` integrity verification.
  - Admin compliance inspection dashboard and statistics in both REST API and Streamlit UI.
- [ ] **Observability & Tracing:**
  - OpenTelemetry, Langfuse, or Arize Phoenix integration to trace latency, token consumption, and retrieval fidelity.
  - Prometheus `/metrics` endpoint with GPU VRAM usage, model load status, queue depth, and request latency histograms.
  - Grafana dashboard templates for production monitoring.
- [x] **One-Command Containerization (Docker & NVIDIA Container Toolkit):**
  - Multi-stage backend image (CPU default, CUDA via build argument), lightweight frontend image, non-root containers, `/health` probe, and GPU passthrough override.
- [ ] **Enterprise SSO & Directory Integration:**
  - SAML 2.0 / OAuth2 integration with Active Directory, Okta, and Keycloak for enterprise-grade authentication.
- [x] **JWT Refresh Token Flow:**
  - Short-lived access tokens + long-lived refresh tokens via `/api/v1/auth/refresh` endpoint.
  - Automatic token refresh in Streamlit UI for seamless user experience.
- [x] **Password Policy Enforcement:**
  - Configurable minimum length, uppercase/lowercase, digit, and special character requirements via environment variables.
  - Enforced on user creation, admin password resets, and self-service password changes.
- [x] **Credential Hardening:**
  - Token revocation on password change or account deactivation, mandatory replacement of the default `admin123` password, and per-account login lockout.
- [x] **Pilot Readiness:**
  - HTTPS reverse proxy, audit and conversation retention with a verifiable hash chain, optional question-text logging, scheduled full backups, telemetry disabled, Turkish/English web UI with an AI disclaimer, and PDF page numbers in citations.
- [x] **Document Access Groups:**
  - Documents restricted to user groups, filtered inside the vector search; group management for admins.
- [x] **Collaborating Agents & Service Requests:**
  - Multi-step plans with answer synthesis, handoffs between agents, and a service request agent with confirmation and e-mail notification through the organization's mail server.
- [ ] **Per-User Data Erasure:**
  - Delete a user's audit entries and conversations on request (KVKK/GDPR right to erasure); today only retention periods remove them.
- [ ] **Multi-Worker Shared State:**
  - Move rate limiting, login throttling, and the user store out of process memory and `users.json` (SQLite or Redis) so the API can run with several workers or replicas.
- [ ] **Multi-Tenant Document Isolation:**
  - Department-level or organization-level document namespace isolation, allowing each tenant to maintain private knowledge bases.
- [x] **ChromaDB Backup & Restore:**
  - Admin API endpoints: `/api/v1/admin/backup`, `/api/v1/admin/backups`, `/api/v1/admin/restore` for point-in-time snapshots and staged restores applied at startup.
- [x] **Dockerfile Multi-Stage Optimization:**
  - Split into builder + runtime stages to reduce production image size by removing `build-essential`, `git`, and development dependencies.

---

## 🛠️ Phase 5 — Code Quality & Developer Experience

> **Priority: Ongoing** — Improvements to maintainability, developer onboarding, and open-source readiness.

- [x] **Legacy Single-Agent Cleanup:**
  - Removed the unused `EnterpriseRAGAgent` graph (`agent_graph.py`, `nodes.py`, `query_service.py`, `tools.py`); the grading helpers live in `src/agent/grading.py`. Package `__init__` files no longer import eagerly (torch, the user store), the Streamlit UI and the database connector are split into focused modules, and tests are grouped by topic.
- [x] **Explicit LLM-Outage Answers:**
  - Questions first check that Ollama answers and has the models (result reused for 10 s); while it is down they get HTTP 503 `llm_unavailable` and the web UI says the language model is not running, instead of the "cannot be fully verified" fallback.
- [x] **Modern Web UI:**
  - A React + TypeScript web UI (`web/`) replaces the Streamlit UI: chat with live progress, requests, and administration, a refresh token in an `HttpOnly` cookie, its own tests in CI, and an nginx image.
- [x] **Agent Collaboration:**
  - Questions back for ambiguous questions, steps that build on earlier steps, a time limit per step, user profiles (unit, program, level), checked database and compliance answers, staff answers to unanswered questions (FAQ) with notifications, request cancel and notes from the chat, per-agent statistics, and an `agents` evaluation stage.
- [x] **Retire the Streamlit UI:**
  - The HTTPS proxy serves the React UI at `/`; `ui/`, `Dockerfile.frontend`, `requirements-ui.txt`, and the `frontend` compose service are removed.
- [x] **Texts per Organization:**
  - Admins set the assistant's name, welcome and disclaimer texts, example questions, example request, and profile field labels in Turkish and English (**Administration → Appearance**); the built-in texts fit any organization.
- [x] **Specific Exception Handling:**
  - Replaced broad `except Exception as e` blocks in the Self-RAG nodes and `jwt_handler.py` with specific exception types (`ConnectionError`, `TimeoutError`, `IOError`, `OSError`, `RuntimeError`).
- [ ] **Async Node Migration:**
  - Evaluate and document the sync-to-async migration path for LangGraph agent nodes to eliminate `asyncio.to_thread()` overhead.
- [x] **Real Database Integration Tests:**
  - CI runs the read-only enforcement tests against PostgreSQL 16 and MySQL 8.4 service containers, bypassing the SQL guard to verify the database-level protection on its own.
- [ ] **Test Coverage Expansion:**
  - Browser tests of the web UI against a running backend (the unit tests run in CI); run the model-backed evaluation (`evals/`) on a GPU runner and gate on quality regressions.
  - Enforce a minimum coverage target (e.g. 80%) as a CI gate; coverage is currently reported but not enforced.
- [x] **CONTRIBUTING.md & Code of Conduct:**
  - Created contributor guidelines, code style guide, and code of conduct for open-source community readiness.
- [x] **CI/CD Pipeline:**
  - GitHub Actions workflow for automated testing (Python 3.12/3.13/3.14), linting and format checks (`ruff`), coverage reporting, and backend/frontend Docker image build validation.
- [ ] **API Versioning Strategy:**
  - Document and enforce `/api/v1/` versioning convention with deprecation policy for future `/api/v2/` migration.
