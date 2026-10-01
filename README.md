# 🏢 OpenLocalRagAgents

[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20AI-blueviolet.svg)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Privacy Protected](https://img.shields.io/badge/Privacy-100%25%20On--Premise-brightgreen.svg)](#)

> **A privacy-first, on-premise generative AI and Agentic RAG platform engineered to run 100% locally on your infrastructure. Prevents enterprise data leakage to third-party cloud providers (OpenAI, Anthropic, etc.) with zero external API dependencies.**

> 📢 **Release v2.1.1:** Correctness and security hardening for the pluggable **Multi-Agent Architecture** (v2.1.0): working multi-turn memory and agent selection, Self-RAG in `doc_agent`, database-enforced read-only SQL, token revocation, and a hash-chained audit trail. Check out the [**Release Notes (WHATSNEW.md)**](WHATSNEW.md) and [**Contributing Guide (CONTRIBUTING.md)**](CONTRIBUTING.md).

---

## ✨ Key Capabilities

* 🤖 **Collaborating Multi-Agent Ecosystem:** A supervisor plans which specialists answer a question (Document & Regulation, SQL Database Analyst, Compliance Auditor, Service Requests, or your own agents). Composite questions run several agents and combine their answers, a failing agent hands the question to another one (e.g. a rejected SQL query goes to the documents), and agents that cannot work (no database connected) are never chosen. Every step is traced.
* 📝 **Service Requests with Confirmation:** Users open requests from the chat ("the projector in B204 is broken, open a ticket"). The assistant shows the draft and files it only after the user says yes; staff work requests off in the UI, and the responsible unit can be e-mailed through the organization's own mail server. No internet access, no other side effects.
* 🗂️ **Document Access Groups:** Documents can be restricted to user groups (e.g. academic staff). The vector search itself filters by the user's groups, so restricted content never reaches the model for users outside those groups.
* 🔒 **100% Local & Air-Gapped:** All embeddings, Cross-Encoder reranking, and LLM inferences execute strictly on your local GPU/CPU. Zero data egress, zero cloud telemetry, and zero token costs.
* 🎯 **Two-Stage Retrieval with a Relevance Gate:** Combines `BAAI/bge-m3` dense vector search with `BAAI/bge-reranker-v2-m3` Cross-Encoder scoring. Passages the reranker scores below `RAG_MIN_RERANKER_SCORE` are dropped, so questions the documents do not answer get "not found in the organization's documents" instead of a guess.
* 🛡️ **Self-Correcting Hallucination Guard (Self-RAG):** `doc_agent` grades each draft answer against the retrieved sources. Unsupported claims are pruned by a refine step; if the answer still cannot be verified, a safe fallback is returned instead of a guess.
* 🔐 **Enterprise Authentication & RBAC:** JWT access/refresh tokens with revocation on password change, bcrypt password hashing, mandatory replacement of the default password, per-account login lockout, and three access tiers (`admin`, `editor`, `viewer`).
* 📜 **Tamper-Evident Compliance Audit Trail:** SQLite-backed audit logging (`data/audit.db`) recording all queries, document uploads/deletions, SQL queries, user logins, and errors with IP tracking and execution latency (ms). Entries form a SHA-256 hash chain verifiable via `GET /api/v1/admin/audit-verify`; export the returned `head_hash` periodically to also detect truncation.
* 🧠 **Multi-Turn Conversational Memory:** Persistent LangGraph SQLite checkpointer (`data/multi_agent_conversations.db`) with user-isolated session threads (`{username}_{session_id}`). The supervisor, document search, and SQL generation all use recent turns, so follow-up questions work.
* 🚀 **LLM Served by Ollama:** The LLM runs in a local [Ollama](https://ollama.com) server (default `qwen2.5:7b`), so the API process loads no LLM weights and switching models is one setting (`OLLAMA_MODEL`). Routing and answer checking can use their own models (`OLLAMA_ROUTER_MODEL`, `OLLAMA_GRADER_MODEL`). Parallel requests are capped by `OLLAMA_NUM_PARALLEL`.
* 🗄️ **Universal Database Connector:** Connects to **PostgreSQL, MSSQL, MySQL, Oracle, and SQLite** via an SQLAlchemy abstraction layer with token-level SQL validation, database-enforced read-only sessions (SQLite/PostgreSQL/MySQL), and automated table vectorization. For production, connect with a SELECT-only database account.
* ⚡ **Progress & Trace UX:** Answers show their stages while they are prepared ("Searching the documents…", "Checking the answer…"), and admins and editors can open the multi-agent trace with actions, durations, and SQL queries.
* 🌐 **Multilingual, Answers in the User's Language:** Multilingual search across enterprise corpora with BGE-M3 dense vectors. Every agent answers in the language of the question (Turkish or English), including fixed messages such as "not found" and error texts, even when the documents or table data are in another language. Mandarin Chinese, Hindi, and Spanish are coming next (see [Language Support](docs/language_support.md)).
* 📏 **Measured Quality:** A labeled evaluation harness (`python -m evals.run_eval`) measures retrieval, routing, and answer accuracy with the real models and compares runs before and after a change (see [Measured Quality](#-measured-quality)).
* 🏛️ **Pilot-Ready Operations:** HTTPS reverse proxy, configurable retention for audit entries and conversations, an option to keep question text out of the audit log, scheduled full backups, and no telemetry (see [Data Protection](docs/data_protection.md)).
* 🖥️ **Full-Stack Suite:** Ready-to-use FastAPI REST gateway (with Swagger OpenAPI docs) paired with a React web UI in Turkish and English (`web/`): chat with live progress, evidence and sources, service requests, and administration, with light and dark themes and an AI disclaimer. The previous Streamlit UI (`ui/`) still works during the transition.

---

## 📊 Measured Quality

Answer quality is measured, not assumed. The [evaluation harness](docs/evaluation.md) runs 51 labeled questions through the real models: document questions, compliance scenarios, database questions, greetings, and questions the documents do not answer.

Default configuration, `qwen2.5:7b` via Ollama on an RTX 3060 Laptop GPU (6 GB):

| Metric | Result |
| :--- | :---: |
| Correct answers (all expected facts present) | **95%** |
| ↳ document / compliance / database questions | 100% / 100% / 80% |
| Questions routed to the right specialist agent | 98% |
| Off-topic questions answered with "not in the documents" instead of a guess | 100% |
| Answerable questions wrongly refused | 2% |
| Answers written in the language of the question | 100% |
| Latency per question (median / 95th percentile) | 7.3 s / 23.2 s |

Before the relevance gate, the routing fixes, and the switch from an in-process 1.5B model to Ollama, the same questions scored 59% correct answers, 0% on database questions, and only half of the off-topic questions were refused. The dataset is small and synthetic, so measure with your own documents before relying on these numbers ([how](docs/evaluation.md#using-your-own-documents)).

---

## 📚 Documentation Hub

Explore our detailed architectural, operational, and development guides:

| Guide | Description |
| :--- | :--- |
| 🚀 [**What's New (v2.1.1)**](WHATSNEW.md) | Release notes, Multi-Agent architecture, API updates, and recent changelog |
| 🤝 [**Contributing Guidelines**](CONTRIBUTING.md) | Contribution standards, development workflows, testing, and PR conventions |
| 🤖 [**Custom Agents Guide**](docs/custom_agents_guide.md) | Step-by-step tutorial on developing and registering custom specialist sub-agents |
| 🏗️ [**System Architecture**](docs/architecture.md) | Multi-agent LangGraph workflow, Self-RAG, two-stage reranking, RBAC, audit trail, and memory |
| 📦 [**Installation & Hardware Matrix**](docs/installation.md) | Hardware requirements, Ollama setup, model provisioning, and configuration |
| 🗄️ [**Database Connectors**](docs/database_connectors.md) | Universal SQLAlchemy configurations, Text-to-SQL security, and ETL table vectorization |
| 🔌 [**REST API Reference**](docs/api_reference.md) | FastAPI endpoint documentation, JWT auth, NDJSON event streaming, and cURL examples |
| 🐳 [**Docker Deployment**](docs/docker_deployment.md) | Production multi-service containerization (Backend, Frontend, Ollama), NVIDIA GPU passthrough |
| 🔏 [**Data Protection (KVKK/GDPR)**](docs/data_protection.md) | Personal data stored, retention settings, backups, and recommended pilot settings |
| 🌍 [**Language Support**](docs/language_support.md) | Supported languages (Turkish, English), behavior for other languages, and languages coming soon (Mandarin Chinese, Hindi, Spanish) |
| 📏 [**Evaluation Guide**](docs/evaluation.md) | Labeled question set, harness, current results, and how each change was measured |
| 🗺️ [**Roadmap**](docs/roadmap.md) | Hybrid search (BM25 + Dense), GraphRAG, observability, SSO, and multi-tenant isolation |

---

## ⚡ Quickstart in 3 Steps

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/SirAlper/OpenLocalRagAgents.git
cd OpenLocalRagAgents

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # Linux/macOS: source .venv/bin/activate

# Install PyTorch (CPU is enough: it only runs the embedding and reranker models) and project requirements
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-ui.txt
```

### 2. Download Models (One-time Setup)
Install [Ollama](https://ollama.com/download) and pull the LLM, then download the embedding and reranker models to `./models`:
```bash
ollama pull qwen2.5:7b
python download_model.py
```

### 3. Launch Services
Make sure Ollama is running (`ollama list` answers), then start the backend and UI in separate terminal windows:

```bash
# Terminal 1: Backend API Gateway (FastAPI)
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
# Interactive Swagger Documentation: http://localhost:8000/docs

# Terminal 2: Web UI (React, needs Node.js 20.19+)
cd web && npm install && npm run dev
# Web UI: http://localhost:5173

# Or the previous Streamlit UI
streamlit run ui/app.py
# Web Dashboard: http://localhost:8501
```

> [!NOTE]
> **Initial Admin Credentials:**
> - **Username:** `admin`
> - **Password:** `admin123`
>
> The built-in default password must be changed at first login (the UI prompts for it; API clients use `POST /api/v1/auth/change-password`). Set `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` in `.env` to seed a different account.

### 4. Or Launch Instantly with Docker 🐳
Run the backend, UI, and Ollama with persistent local volumes. Optionally copy `.env.example` to `.env` first; the backend container reads it. The LLM is pulled automatically on the first start:
```bash
# CPU Mode:
docker compose up -d

# NVIDIA GPU Mode (GPU for Ollama):
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# HTTPS for shared deployments (certificates in deploy/certs/):
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```
See the full [Docker Deployment Guide](docs/docker_deployment.md) for Container Toolkit setup.

### 5. Run Automated Tests
Install the development tooling and run the unit, end-to-end, and security test suite (tests use an isolated temporary data directory and a stubbed LLM, so Ollama is not needed; model-dependent profiling tests are skipped when weights are not downloaded):
```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## 📁 Repository Structure

```text
OpenLocalRagAgents/
├── data/                  # Documents (PDF, DOCX, TXT), sample DB, audit.db, conversations, requests.db, users.json
├── models/                # Local retrieval model weights (BGE-M3, BGE-Reranker); the LLM lives in Ollama
├── vector_db/             # ChromaDB persistent vector collection
├── backups/               # Full backups (index + data) and staged index restores
├── tests/                 # Tests by topic: agents/, rag/, api/, security/, data/, frontend/, quality/, performance/
├── evals/                 # Quality evaluation harness (labeled datasets, corpora incl. a university law, run_eval.py)
│
├── web/                   # Web UI: React + TypeScript + Vite (chat, requests, admin), Dockerfile with nginx
├── ui/                    # Streamlit UI: app.py (chat), sidebar.py, components.py, api_client.py, session.py, i18n.py
├── src/
│   ├── core/              # Infrastructure: settings (config), logging, hash-chained audit trail
│   ├── auth/              # JWT tokens, user store, roles, password policy, login throttling, document access groups
│   ├── rag/               # Document loader (contextual chunks, page numbers) and two-stage retrieval engine
│   ├── agent/             # LLM access (Ollama), prompts, response language, answer grading
│   │   └── multi_agent/   # Supervisor (plans), orchestrator (handoffs, synthesis), registry, specialist sub-agents
│   ├── connectors/        # Read-only database connector, SQL guard, sample database, table vectorizer
│   ├── services/          # Documents, databases, backups, service requests, e-mail notifications
│   ├── api/               # FastAPI app: routes/, schemas, shared state, scheduled maintenance
│   └── main.py            # Launch target (uvicorn src.main:app)
├── docs/                  # Comprehensive Technical Guides (docs/)
├── .github/workflows/     # CI: lint, tests (Python 3.12-3.14), PostgreSQL/MySQL integration, Docker builds
├── examples/              # Developer examples (custom sub-agents)
├── Dockerfile             # Backend multi-stage image (CPU default, CUDA via build arg)
├── Dockerfile.frontend    # Lightweight Streamlit UI image
├── docker-compose.yml     # Multi-service compose definition (Backend + Web + Streamlit + Ollama)
├── docker-compose.gpu.yml # NVIDIA GPU passthrough override
├── docker-compose.https.yml # HTTPS reverse proxy override (nginx)
├── deploy/                # nginx configuration and TLS certificate folder
├── download_model.py      # Downloads the embedding and reranker models to ./models
├── requirements.txt       # Backend runtime dependencies
├── requirements-ui.txt    # Streamlit UI dependencies
├── requirements-dev.txt   # Test & lint tooling
├── .env.example           # Every setting with its default and a comment
├── ruff.toml              # Lint and format settings (same as CI)
├── WHATSNEW.md            # Release notes and changelog
├── CONTRIBUTING.md        # Contribution guidelines and development workflow
└── LICENSE                # MIT License
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
