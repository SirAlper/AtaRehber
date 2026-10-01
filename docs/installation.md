# 📦 Installation & Hardware Guide

This guide provides step-by-step instructions for deploying `OpenLocalRagAgents` on local workstations or enterprise on-premise servers with hardware acceleration.

---

## 💻 System & Hardware Requirements

The LLM runs in a local [Ollama](https://ollama.com) server; the API process only loads the embedding and reranker models.

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **Operating System** | Ubuntu 22.04 LTS / Windows 11 / macOS | Ubuntu 22.04 LTS / Windows 11 / RHEL 9 |
| **Python** | 3.12+ | 3.12 or 3.13 |
| **System RAM** | 8 GB | 16 GB - 32 GB |
| **GPU / VRAM** | Optional (Ollama also runs on CPU, slowly) | NVIDIA GPU with 6 GB+ VRAM for `qwen2.5:7b`, 12 GB+ for 14B models |
| **Ollama** | Latest release | Latest release |

> **Memory Allocation (default settings):**  
> - `bge-m3` embedding model: ~1.1 GB RAM (CPU, in the API process)  
> - `bge-reranker-v2-m3` reranker model: ~1.1 GB RAM (CPU, in the API process)  
> - `qwen2.5:7b` LLM: ~4.7 GB, 4-bit quantized by Ollama, in VRAM when a GPU is available  
> - Smaller GPUs: `qwen2.5:3b` (~1.9 GB) fits in 4 GB of VRAM. Measure the quality difference with the [evaluation harness](evaluation.md).

---

## 🛠️ Step-by-Step Installation

### 1. Clone the Repository
```bash
git clone https://github.com/SirAlper/OpenLocalRagAgents.git
cd OpenLocalRagAgents
```

### 2. Create and Activate Virtual Environment
```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install PyTorch

PyTorch only runs the embedding and reranker models, which use the CPU by default (`RAG_DEVICE=cpu`) so the GPU stays free for Ollama. The CPU build is enough:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```
To run retrieval on an NVIDIA GPU instead, install a CUDA build (e.g. `--index-url https://download.pytorch.org/whl/cu121`) and set `RAG_DEVICE=cuda`.

### 4. Install Project Dependencies
```bash
pip install --upgrade pip
# Backend (use requirements-dev.txt instead for tests and linting)
pip install -r requirements.txt
```

### 5. Install Ollama and Pull the LLM
Install Ollama from [ollama.com/download](https://ollama.com/download), then pull the default model:
```bash
ollama pull qwen2.5:7b
ollama list            # the model should be listed; this also confirms the server is running
```
To use another model, pull it and set `OLLAMA_MODEL` in `.env`. The API logs a clear error at startup (and `GET /api/v1/stats` reports `llm_status`) if the server is unreachable or the model has not been pulled.

---

## ⚙️ Configuration & Environment Variables (`.env`)

Create a `.env` file in the root directory (loaded automatically via `python-dotenv`):

```env
# ─── Authentication & RBAC ───
ADMIN_DEFAULT_USERNAME=admin
ADMIN_DEFAULT_PASSWORD=admin123
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
# Web UI: send its refresh token cookie over HTTPS only (true behind HTTPS; the HTTPS compose sets it):
REFRESH_COOKIE_SECURE=false
# The default admin123 password must be changed at first login:
REQUIRE_DEFAULT_PASSWORD_CHANGE=true
# Temporary per-account lockout after repeated failed logins:
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_WINDOW_SECONDS=900
# Optional custom HMAC secret (randomly generated and persisted to data/.jwt_secret if unset):
# JWT_SECRET_KEY=

# ─── Password Strength Policy ───
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=true
PASSWORD_REQUIRE_LOWERCASE=true
PASSWORD_REQUIRE_DIGIT=true
PASSWORD_REQUIRE_SPECIAL=false

# ─── LLM (Ollama) ───
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_CTX=4096
# Layers on the GPU (empty = Ollama decides; 99 = all, e.g. qwen2.5:7b on a 6 GB card):
OLLAMA_NUM_GPU=
OLLAMA_NUM_PARALLEL=4
# Optional separate models for routing and answer grading (empty = OLLAMA_MODEL):
OLLAMA_ROUTER_MODEL=
OLLAMA_GRADER_MODEL=
# Answer check: quotes (facts backed by copied sentences) or simple (yes/no):
GRADER_MODE=quotes
# Answer check: second opinion on rejections, number check, transitional-article check:
GRADER_SECOND_OPINION=true
GRADER_NUMBER_CHECK=true
GRADER_TRANSITIONAL_CHECK=true
# Reuse verified answers to first questions (0 = off):
ANSWER_CACHE_SIZE=256
ANSWER_CACHE_MINUTES=1440
# Experimental answer modes (off by default):
ANSWER_EVIDENCE_FIRST=false
DOC_AGENT_TOOLS=false

# ─── Organization & Agents ───
ORGANIZATION_NAME=
MAX_AGENT_STEPS=3
MAX_AGENT_HANDOFFS=1
# Ask one question back when the answer depends on something the user did not say ("Kaç gün izin hakkım var?")
CLARIFY_QUESTIONS=true
# Seconds an agent step may take before it is given up and the other steps are answered (0 = no limit)
AGENT_STEP_TIMEOUT_SECONDS=180

# ─── Service Requests & E-mail (off unless SMTP_HOST is set) ───
REQUEST_CATEGORIES=it_support,facilities,academic,administrative,other
REQUEST_NOTIFY_EMAILS=
REQUEST_NOTIFY_INCLUDE_DETAILS=true
REQUEST_RETENTION_DAYS=0
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_STARTTLS=true
SMTP_TIMEOUT_SECONDS=10

# ─── Relational Database (Optional) ───
# Supports PostgreSQL, MSSQL, MySQL, Oracle, SQLite.
# Leave empty to use the sample SQLite database generated in data/ on first start,
# or set SAMPLE_DB_ENABLED=false to run without a database.
DATABASE_URL=
SAMPLE_DB_ENABLED=true
DB_ALLOWED_TABLES=urunler,satislar,destek_talepleri
DB_MAX_ROWS=50
DB_QUERY_TIMEOUT_SECONDS=15

# ─── API & Security Settings ───
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
MAX_UPLOAD_SIZE_MB=50
RATE_LIMIT_PER_MINUTE=30
RATE_LIMIT_READS_PER_MINUTE=300
# Guest access (visitors without an account, documents of GUEST_DOCUMENT_GROUP only):
GUEST_ACCESS_ENABLED=false
GUEST_DOCUMENT_GROUP=ziyaretci
GUEST_SESSION_MINUTES=120
GUEST_RATE_LIMIT_PER_MINUTE=10
MAX_QUEUED_QUERIES=10

# ─── Contextual Chunking & Retrieval ───
CHUNK_SIZE=600
CHUNK_OVERLAP=100
ARTICLE_CHUNK_SIZE=900
RAG_CANDIDATE_POOL=10
RERANKER_TOP_N=4
RAG_MIN_SIMILARITY=0.325
RAG_MIN_RERANKER_SCORE=0.005

# ─── Conversation Memory ───
CHAT_HISTORY_MAX_TURNS=20

# ─── Data Protection & Backups (see docs/data_protection.md) ───
AUDIT_STORE_QUESTIONS=true
AUDIT_RETENTION_DAYS=0
SESSION_RETENTION_DAYS=0
BACKUP_INTERVAL_HOURS=0
BACKUP_KEEP=7

# ─── Web UI ───
# Default language and a disclaimer for both languages; the name, welcome text, and example questions are set
# under Administration → Appearance
UI_LANGUAGE=tr
# UI_DISCLAIMER=Answers are AI-generated. For official information contact the relevant department.

# ─── Logging Settings ───
LOG_LEVEL=INFO
LOG_FILE=app.log

# ─── Model & Hardware Execution ───
RAG_DEVICE=cpu
ALLOW_ONLINE_HF=0

# ─── Storage ───
# Directory for documents, users, audit log, JWT secret, and conversation memory:
# DATA_DIR=data
```

The complete, commented list of settings is in [`.env.example`](../.env.example).

---

## 📥 Provisioning Models Locally (`download_model.py`)

The embedding and reranker models are pinned into the project's `./models/` directory (~3.3 GB) to prevent runtime downloads and avoid inflating `~/.cache`. The LLM is not part of this: Ollama stores it (`ollama pull`).

Run the provisioning script:
```bash
python download_model.py
```

* **Smart Verification & Skip Logic:** The script checks if model weights already exist on disk and skips re-downloading.
* **Force Re-Download:** If you need to re-download corrupted weights, set `FORCE_DOWNLOAD=1`:
  ```bash
  FORCE_DOWNLOAD=1 python download_model.py
  ```
  In PowerShell, set the variable separately: `$env:FORCE_DOWNLOAD = "1"; python download_model.py; Remove-Item Env:FORCE_DOWNLOAD`

Once both the retrieval models and the Ollama model are downloaded, the system operates in **100% offline (air-gapped)** mode with zero internet access required.

---

## 🧪 Running Automated Tests & Code Quality

Install the development tooling, then run the unit, end-to-end, and security test suite:

```bash
pip install -r requirements-dev.txt

# Run the tests:
pytest tests/ -v

# Run with test coverage report:
pytest tests/ --cov=src --cov-report=term-missing

# Lint and formatting checks (same as CI; settings in ruff.toml):
ruff check src/ tests/ evals/
ruff format --check src/ tests/ evals/
```

Tests run against an isolated temporary data directory (see `tests/conftest.py`) and never touch your `data/` folder. LLM calls are stubbed, so tests do not need Ollama. Tests are grouped by topic (`tests/agents/`, `rag/`, `api/`, `security/`, `data/`, `quality/`, `performance/`). The memory-profiling tests in `tests/performance/` load the real embedding models and run only with `RUN_PROFILE_TESTS=1`.

---

## 🚀 Launching Services

### Backend (FastAPI Gateway):
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
# or: python -m src.main
```
* **Interactive Swagger Documentation:** `http://localhost:8000/docs`

> [!TIP]
> Avoid `--reload` outside development: every file change restarts the API and reloads the embedding and reranker models (~2 GB).

### Web UI (React):
Needs [Node.js](https://nodejs.org/) 20.19 or newer (Vite 7). In a separate terminal window:
```bash
cd web
npm install        # once
npm run dev        # http://localhost:5173, forwards /api to the backend on port 8000
```
* **Web UI:** `http://localhost:5173` (another backend address: `API_URL=http://host:8000 npm run dev`)
* **Production build:** `npm run build` writes static files to `web/dist/`; serve them with the `web` Docker service or any web server that forwards `/api` to the backend and answers unknown paths with `index.html`.
* **Checks:** `npm run typecheck` and `npm test`.

> [!NOTE]
> **Initial Admin Credentials:**
> - **Username:** `admin`
> - **Password:** `admin123`
>
> The built-in default password must be changed at first login (the UI prompts for it; API clients use `POST /api/v1/auth/change-password`). Set `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` in `.env` to seed a different account.

---

## 🩺 Troubleshooting

| Symptom | Cause and fix |
| :--- | :--- |
| Startup log: `[LLM] Ollama server is not reachable` | Ollama is not running. Start the Ollama app (Windows/macOS) or `ollama serve` (Linux). If it runs on another machine, set `OLLAMA_BASE_URL`. |
| Startup log: `Ollama model '…' is not pulled` | Run `ollama pull <model>` for the model in `OLLAMA_MODEL`. |
| Every answer says *"This information cannot be fully verified against company documents."* | Often the LLM is unavailable, not the documents. Check `llm_status` in `GET /api/v1/stats` or the UI sidebar. |
| The first answer takes about a minute, later ones a few seconds | Ollama loads the model on first use and unloads it after 5 idle minutes. Keep it loaded longer with the Ollama server setting `OLLAMA_KEEP_ALIVE` (for example `30m`). |
| Answers are slow on a small GPU | `ollama ps` shows how much of the model runs on the CPU (for example `18%/82% CPU/GPU`). Use a smaller model such as `qwen2.5:3b` or close other GPU applications, and compare the quality with the [evaluation harness](evaluation.md). |
| A question is answered "not found" although a document covers it | The relevance gate (`RAG_MIN_RERANKER_SCORE`) may be too strict for your documents. Measure with your own questions ([how](evaluation.md#using-your-own-documents)). |
| Log: `Ignoring LLM_BACKEND, …` | Settings of the removed HuggingFace backend are still in `.env`; delete them. |
| `VAR=value python …` fails in PowerShell | That syntax is for bash. In PowerShell use `$env:VAR = "value"` on its own line, run the command, then `Remove-Item Env:VAR`. |
