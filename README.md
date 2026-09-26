# 🏢 OpenLocalRagAgents

[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20AI-blueviolet.svg)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Privacy Protected](https://img.shields.io/badge/Privacy-100%25%20On--Premise-brightgreen.svg)](#)

> **A privacy-first, on-premise generative AI and Agentic RAG platform engineered to run 100% locally on your infrastructure. Prevents enterprise data leakage to third-party cloud providers (OpenAI, Anthropic, etc.) with zero external API dependencies.**

> 📢 **Release v2.1.1:** Correctness and security hardening for the pluggable **Multi-Agent Architecture** (v2.1.0): working multi-turn memory and agent selection, Self-RAG in `doc_agent`, database-enforced read-only SQL, token revocation, and a hash-chained audit trail. Check out the [**Release Notes (WHATSNEW.md)**](WHATSNEW.md) and [**Contributing Guide (CONTRIBUTING.md)**](CONTRIBUTING.md).

---

## ✨ Key Capabilities

* 🤖 **Pluggable Multi-Agent Ecosystem:** Dynamic Supervisor Orchestrator with runtime intent analysis, routing to specialist Sub-Agents (Document RAG, SQL Database Analyst, Compliance Auditor) with millisecond-precision execution tracing.
* 🔒 **100% Local & Air-Gapped:** All embeddings, Cross-Encoder reranking, and LLM inferences execute strictly on your local GPU/CPU. Zero data egress, zero cloud telemetry, and zero token costs.
* 🎯 **Two-Stage Retrieval:** Combines `BAAI/bge-m3` dense vector search with `BAAI/bge-reranker-v2-m3` Cross-Encoder scoring to extract pinpoint enterprise context within milliseconds.
* 🛡️ **Self-Correcting Hallucination Guard (Self-RAG):** `doc_agent` grades each draft answer against the retrieved sources. Unsupported claims are pruned by a refine step; if the answer still cannot be verified, a safe fallback is returned instead of a guess.
* 🔐 **Enterprise Authentication & RBAC:** JWT access/refresh tokens with revocation on password change, bcrypt password hashing, mandatory replacement of the default password, per-account login lockout, and three access tiers (`admin`, `editor`, `viewer`).
* 📜 **Tamper-Evident Compliance Audit Trail:** SQLite-backed audit logging (`data/audit.db`) recording all queries, document uploads/deletions, SQL queries, user logins, and errors with IP tracking and execution latency (ms). Entries form a SHA-256 hash chain verifiable via `GET /api/v1/admin/audit-verify`; export the returned `head_hash` periodically to also detect truncation.
* 🧠 **Multi-Turn Conversational Memory:** Persistent LangGraph SQLite checkpointer (`data/multi_agent_conversations.db`) with user-isolated session threads (`{username}_{session_id}`). The supervisor, document search, and SQL generation all use recent turns, so follow-up questions work.
* 🚀 **Dual Serving Backends (HuggingFace & Ollama):** Run in-process with local BF16 models (`Qwen2.5-1.5B`) or seamlessly connect to external high-concurrency Ollama instances (`qwen2.5:7b`, `llama3.1:8b`) with adaptive concurrency gating.
* 🗄️ **Universal Database Connector:** Connects to **PostgreSQL, MSSQL, MySQL, Oracle, and SQLite** via an SQLAlchemy abstraction layer with token-level SQL validation, database-enforced read-only sessions (SQLite/PostgreSQL/MySQL), and automated table vectorization. For production, connect with a SELECT-only database account.
* ⚡ **Thinking Indicator & Trace UX:** Streamlined user experience featuring interactive thinking indicators and collapsible multi-agent execution traces showing internal actions, durations, and SQL queries.
* 🌐 **Language-Agnostic & Multilingual:** Native multilingual search across enterprise corpora powered by BGE-M3 dense vectors, responding naturally in the user's language without artificial constraints.
* 🖥️ **Full-Stack Suite:** Ready-to-use FastAPI REST gateway (with Swagger OpenAPI docs) paired with a modern Streamlit enterprise control panel.

---

## 📚 Documentation Hub

Explore our detailed architectural, operational, and development guides:

| Guide | Description |
| :--- | :--- |
| 🚀 [**What's New (v2.1.1)**](WHATSNEW.md) | Release notes, Multi-Agent architecture, API updates, and recent changelog |
| 🤝 [**Contributing Guidelines**](CONTRIBUTING.md) | Contribution standards, development workflows, testing, and PR conventions |
| 🤖 [**Custom Agents Guide**](docs/custom_agents_guide.md) | Step-by-step tutorial on developing and registering custom specialist sub-agents |
| 🏗️ [**System Architecture**](docs/architecture.md) | Multi-agent LangGraph workflow, Self-RAG, two-stage reranking, RBAC, audit trail, and memory |
| 📦 [**Installation & Hardware Matrix**](docs/installation.md) | VRAM/RAM hardware requirements, CUDA 12.1 setup, Ollama integration, and offline provisioning |
| 🗄️ [**Database Connectors**](docs/database_connectors.md) | Universal SQLAlchemy configurations, Text-to-SQL security, and ETL table vectorization |
| 🔌 [**REST API Reference**](docs/api_reference.md) | FastAPI endpoint documentation, JWT auth, NDJSON event streaming, and cURL examples |
| 🐳 [**Docker Deployment**](docs/docker_deployment.md) | Production multi-service containerization (Backend, Frontend, Ollama), NVIDIA GPU passthrough |
| 📏 [**Evaluation Guide**](docs/evaluation.md) | Labeled question set and harness measuring retrieval, routing, and answer quality |
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

# Install PyTorch (CUDA 12.1 recommended) and project requirements
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt -r requirements-ui.txt
```

### 2. Download Models Locally (One-time Setup)
Download model weights directly to `./models` to enable offline air-gapped inference:
```bash
python download_model.py
```

### 3. Launch Services
Run the backend and UI in separate terminal windows:

```bash
# Terminal 1: Backend API Gateway (FastAPI)
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
# Interactive Swagger Documentation: http://localhost:8000/docs

# Terminal 2: Enterprise Web Management UI (Streamlit)
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
Run the backend and UI with persistent local volumes. Optionally copy `.env.example` to `.env` first; the backend container reads it:
```bash
# CPU Mode:
docker compose up -d

# NVIDIA GPU Mode (CUDA Passthrough):
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# With Optional Ollama Serving Profile:
docker compose --profile ollama up -d
```
See the full [Docker Deployment Guide](docs/docker_deployment.md) for Container Toolkit setup.

### 5. Run Automated Tests
Install the development tooling and run the unit, end-to-end, and security test suite (tests use an isolated temporary data directory; model-dependent profiling tests are skipped when weights are not downloaded):
```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## 📁 Repository Structure

```text
OpenLocalRagAgents/
├── data/                  # Documents (PDF, DOCX, TXT), sample DB, audit.db, multi_agent_conversations.db, users.json
├── models/                # Local model weights (Qwen2.5-1.5B, BGE-M3, BGE-Reranker)
├── vector_db/             # ChromaDB persistent vector collection
├── backups/               # Vector DB snapshots and staged restores
├── tests/                 # Automated unit, end-to-end, and security test suite
├── evals/                 # Quality evaluation harness (labeled dataset, corpus, run_eval.py)
│
├── ui/
│   └── app.py             # Streamlit enterprise management dashboard, RBAC chat & audit UI
├── src/
│   ├── core/              # System configurations, audit logger, environment settings, and logger
│   ├── auth/              # Enterprise JWT handler, user store, password hashing, and RBAC dependencies
│   ├── rag/               # Contextual document loader and Two-Stage ChromaDB/Reranker engine
│   ├── agent/             # Single-agent & Multi-Agent workflows, LLM loader, memory, prompts
│   │   └── multi_agent/   # Supervisor orchestrator, agent registry, and specialist sub-agents
│   ├── connectors/        # SQLAlchemy universal database connector and table vectorizer
│   ├── services/          # Decoupled business logic (DocumentService, DatabaseService)
│   ├── api/               # Modular FastAPI REST API gateway (routes/, schemas, state)
│   └── main.py            # Backward-compatible launch entrypoint (uvicorn src.main:app)
├── docs/                  # Comprehensive Technical Guides (docs/)
├── examples/              # Developer examples (custom sub-agents)
├── Dockerfile             # Backend multi-stage image (CPU default, CUDA via build arg)
├── Dockerfile.frontend    # Lightweight Streamlit UI image
├── docker-compose.yml     # Multi-service compose definition (Backend + Frontend + Ollama)
├── docker-compose.gpu.yml # NVIDIA GPU passthrough override
├── download_model.py      # Script to download HuggingFace model weights to local storage
├── requirements.txt       # Backend runtime dependencies
├── requirements-ui.txt    # Streamlit UI dependencies
├── requirements-dev.txt   # Test & lint tooling
├── WHATSNEW.md            # Release notes and changelog
├── CONTRIBUTING.md        # Contribution guidelines and development workflow
└── LICENSE                # MIT License
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
