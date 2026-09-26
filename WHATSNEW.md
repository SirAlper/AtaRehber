# 🚀 What's New in OpenLocalEnterpriseRag

This document provides a comprehensive log of new features, architectural upgrades, system components, API endpoints, and user experience enhancements introduced in **OpenLocalEnterpriseRag**.

---

## 🔧 Version 2.1.1 — Correctness & Security Hardening

### Fixed
* **Multi-turn memory in the multi-agent workflow:** turns are now appended to `chat_history` by a `record_turn` graph node and persisted per session by the checkpointer. Previously history was never written, so follow-up questions had no context.
* **Forced agent selection:** `forced_agent` is now part of `MultiAgentState`; LangGraph had been silently dropping it, so the UI agent selector had no effect on `/api/v1/query`.
* **Streaming uses the same graph as batch queries:** `/api/v1/query-stream` now shares memory and routing with `/api/v1/query`. A client disconnect stops the worker and keeps the concurrency gate until inference finishes.
* **Self-RAG restored:** `doc_agent` now grades answers, refines ungrounded drafts, and falls back safely. Grader failures count as unverified (fail closed). `hallucination_grade` / `is_refined` are populated again.
* **`db_agent`:** reports the real guard/database error message and row count; splits generated SQL with `sqlparse`, so semicolons inside string literals are handled.
* **Table re-sync** now removes previously indexed rows (the delete used a different source name than indexing).
* **Session cleanup** honors `max_age_days` and targets the multi-agent conversation store (it previously deleted every session in the legacy store).
* **Docker:** `/health` liveness endpoint; the old healthcheck hit an authenticated endpoint, so the frontend never started.
* **Docker configuration:** the backend now loads `.env` via `env_file`, and compose defaults use `${VAR:-default}`, so settings such as `LLM_BACKEND=ollama` in `.env` take effect. Previously `.env` only worked because it was copied into the image.
* **Docker backups & restore:** `./backups` is mounted (snapshots were lost when the container was recreated). The restore now swaps the vector DB's contents instead of renaming the directory, which failed on the bind mount.
* **Fresh installs:** the auto-generated sample database is connected on the first start instead of only after a restart.
* **Agents registered at runtime** are now routable: the orchestrator recompiles its workflow when the registry changes (they previously produced an empty answer). If the supervisor falls back and no `doc_agent` is registered, the user gets an explanatory message instead of an empty answer.
* **CI** now runs on `master`, uses a pinned ruff, and does not download model weights.

### Security
* Refresh tokens are no longer accepted as access tokens; password changes and account deactivation revoke existing tokens.
* The default `admin123` password must be changed at first login (`POST /api/v1/auth/change-password`); the password policy now also applies to password resets.
* Per-account login lockout after repeated failures; general rate limiting is per account instead of per IP.
* SQL guard rewritten with token-level analysis. It blocks multi-statements, `SELECT INTO`, `ATTACH`/`PRAGMA`, and file/network/sleep functions, and enforces the table allowlist across comma joins, quoted and schema-qualified names, and subqueries. Queries also run in database-enforced read-only sessions (SQLite `query_only`, PostgreSQL/MySQL read-only transactions with a statement timeout).
* Audit log entries form a SHA-256 hash chain; `GET /api/v1/admin/audit-verify` detects edited or deleted entries.
* Vector DB restore is staged and applied at startup instead of deleting the live database under a running server.
* The auto-generated JWT secret file (`data/.jwt_secret`) is created with owner-only permissions (`0600`) on POSIX systems.
* Internal exception details are no longer returned to API clients; questions are logged only at DEBUG level.

### Operations
* Separate lightweight `Dockerfile.frontend`; backend image defaults to CPU PyTorch (CUDA via the `docker-compose.gpu.yml` build arg) and runs as a non-root user.
* Requirements split into `requirements.txt` (backend), `requirements-ui.txt`, and `requirements-dev.txt`, with major-version upper bounds.
* New settings: `DATA_DIR`, `RERANKER_TOP_N`, `RAG_MIN_SIMILARITY`, `CHAT_HISTORY_MAX_TURNS`, `DB_QUERY_TIMEOUT_SECONDS`, `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_WINDOW_SECONDS`, `REQUIRE_DEFAULT_PASSWORD_CHANGE`.
* New vector collections use cosine distance; the similarity threshold is metric-independent, so existing L2 indexes keep working unchanged.

---

## 🌟 Version 2.1.0 — Pluggable Multi-Agent Ecosystem

OpenLocalEnterpriseRag has evolved from a single-agent RAG pipeline into an **extensible, modular, and pluggable Multi-Agent framework** powered by LangGraph. The platform now features an intelligent **Supervisor Orchestrator** paired with domain-specific **Specialist Sub-Agents**, complete with real-time execution trace auditing.

---

### 1. 🏗️ Modular Multi-Agent Framework (`src/agent/multi_agent/`)

A production-grade multi-agent architecture has been integrated into the core system:

* **[`BaseSubAgent`](src/agent/multi_agent/base.py)**:
  * Abstract base class defining the contract for all specialist sub-agents.
  * Standardized attributes (`name`, `display_name`, `description`, `version`) and execution lifecycle (`execute(state)`).
  * Direct access to shared local LLM backends (`chat_model`).

* **[`AgentRegistry`](src/agent/multi_agent/registry.py) & `@register_agent`**:
  * Central dynamic registry implementing the Registry Pattern.
  * Developers can register custom sub-agents with a single `@register_agent` class decorator.
  * Self-discovering metadata engine feeding the Supervisor router and REST API dynamically.

* **[`MultiAgentState`](src/agent/multi_agent/state.py)**:
  * Typed LangGraph state container handling question context, user identity, conversation thread ID, active routing target (`active_agent`), step-by-step audit trace (`agent_trace`), grounded citations, and hallucination verdicts.

* **[`SupervisorAgent`](src/agent/multi_agent/supervisor.py)**:
  * Central intent classifier and dynamic router.
  * Inspects registry metadata at runtime to route queries to the most suitable sub-agent or handles general conversational inquiries directly without triggering downstream retrieval.
  * Built-in guardrails, regex-based fast paths, and fallback mechanisms.

* **[`MultiAgentOrchestrator`](src/agent/multi_agent/orchestrator_graph.py)**:
  * Compiled LangGraph `StateGraph` managing node transitions, conditional routing edges, and execution loops.
  * Persistent SQLite checkpointer (`MemorySaver` / `multi_agent_conversations.db`) for user-isolated conversation memory.
  * Full support for synchronous queries (`query()`), real-time NDJSON event streaming (`stream_events()`), and explicit agent targeting (`forced_agent`).

---

### 2. 👥 Built-in Specialist Sub-Agents (`src/agent/multi_agent/sub_agents/`)

Three enterprise specialist sub-agents are packaged out of the box:

| Agent Identifier | Display Name | Domain Specialization |
| :--- | :--- | :--- |
| **`doc_agent`** | 📄 Document & Policy RAG Specialist | Dense vector retrieval (BGE-M3) with Cross-Encoder reranking over company documents (PDF, DOCX, TXT) with verified citations. |
| **`db_agent`** | 🗄️ SQL & Database Analyst | Schema inspection and AST-validated read-only SQL generation across relational databases (PostgreSQL, MySQL, SQLite, etc.) with automated result summarization. |
| **`compliance_agent`** | 🛡️ Enterprise Compliance Auditor | Formal corporate compliance evaluations checking queries against company policies and GDPR/KVKK rules, rendering structured verdicts (`COMPLIANT`, `WARNING`, `VIOLATION`). |

---

### 3. 🌐 REST API Gateway Upgrades (`src/api/`)

FastAPI services now natively support multi-agent routing and introspection:

* **New Endpoint — `GET /api/v1/agents`**:
  * Returns a dynamic catalog of all active sub-agents along with their capabilities, version, and display metadata.
* **Enhanced Endpoint — `POST /api/v1/query`**:
  * Accepts an optional `agent` parameter in [`QueryRequest`](src/api/schemas.py) (`auto` for Supervisor routing, or explicit sub-agent IDs).
  * Returns `active_agent` and a detailed `agent_trace` array capturing execution metrics, SQL queries, and search parameters.
* **Streaming Endpoint — `POST /api/v1/query-stream`**:
  * Emits streaming multi-agent event frames via NDJSON, including real-time active agent tags and audit milestones.
* **State Management (`src/api/state.py`)**:
  * Singleton provider `get_multi_agent_orchestrator()` with clean lifecycle resource disposal during shutdown.

---

### 4. 🎨 Enterprise Streamlit UI Enhancements (`ui/app.py`)

The enterprise web dashboard delivers transparent multi-agent visibility:

* **🤖 Specialist Agent Team Selector**:
  * Dynamic sidebar dropdown populated directly from `/api/v1/agents`, enabling users to select the automatic supervisor or force-delegate tasks to a specific specialist.
* **🏷️ Color-Coded Agent Badges**:
  * Distinct badges preceding assistant responses to denote the answering agent:
    * 👑 **Supervisor** (Direct Response)
    * 📄 **doc_agent** (Document RAG Specialist)
    * 🗄️ **db_agent** (SQL & Database Analyst)
    * 🛡️ **compliance_agent** (Enterprise Compliance Auditor)
* **🔍 Collapsible Execution Trace Panel**:
  * Interactive accordion below each response revealing internal execution steps, duration in milliseconds, generated SQL queries, and retrieval parameters.

---

### 5. 📚 Developer Guides & Reference Examples

* **[`docs/custom_agents_guide.md`](docs/custom_agents_guide.md)**:
  * Complete 3-step developer tutorial for creating custom sub-agents using `BaseSubAgent` and `@register_agent`.
* **[`examples/custom_agent_example.py`](examples/custom_agent_example.py)**:
  * Fully executable sample demonstrating a `CurrencyConverterAgent` with custom math processing and multi-agent integration.

---

### 6. 🧪 Comprehensive Test Suite

* **[`tests/test_multi_agent.py`](tests/test_multi_agent.py)**:
  * Unit tests validating `BaseSubAgent`, `AgentRegistry`, `SupervisorAgent`, state handling, and LangGraph workflow orchestration.
* **[`tests/test_api_multi_agent.py`](tests/test_api_multi_agent.py)**:
  * Integration tests for `/api/v1/agents` authentication, response contracts, supervisor routing, and streaming output.

---

## 📋 File Modifications Summary

| Directory / File | Status | Description |
| :--- | :--- | :--- |
| `src/agent/multi_agent/base.py` | ✨ Added | Base abstract class (`BaseSubAgent`) for sub-agents |
| `src/agent/multi_agent/registry.py` | ✨ Added | Central agent registry and `@register_agent` decorator |
| `src/agent/multi_agent/state.py` | ✨ Added | Multi-Agent LangGraph state models |
| `src/agent/multi_agent/supervisor.py` | ✨ Added | Intelligent Supervisor intent classifier and router |
| `src/agent/multi_agent/orchestrator_graph.py` | ✨ Added | Compiled LangGraph multi-agent execution workflow |
| `src/agent/multi_agent/sub_agents/doc_agent.py` | ✨ Added | Document vector RAG specialist sub-agent |
| `src/agent/multi_agent/sub_agents/db_agent.py` | ✨ Added | SQL database analysis and safe query sub-agent |
| `src/agent/multi_agent/sub_agents/compliance_agent.py` | ✨ Added | Regulatory compliance and policy auditor sub-agent |
| `src/api/routes/query.py` | 📝 Modified | Added `/api/v1/agents` endpoint and multi-agent routing |
| `src/api/schemas.py` | 📝 Modified | Added `AgentInfo`, `AgentsListResponse`, and `agent` query field |
| `src/api/state.py` | 📝 Modified | Added `get_multi_agent_orchestrator()` and cleanup |
| `src/api/main.py` | 📝 Modified | Exported multi-agent orchestrator dependencies |
| `ui/app.py` | 📝 Modified | Added agent selector dropdown, badges, and trace panel |
| `docs/custom_agents_guide.md` | ✨ Added | Developer guide for building custom sub-agents |
| `examples/custom_agent_example.py` | ✨ Added | Working sample custom sub-agent implementation |
| `tests/test_multi_agent.py` | ✨ Added | Core multi-agent framework unit test suite |
| `tests/test_api_multi_agent.py` | ✨ Added | Multi-agent API integration test suite |
| `WHATSNEW.md` | ✨ Added | Comprehensive release notes and changelog |
