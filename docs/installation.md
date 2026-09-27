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
# Backend + Streamlit UI (add requirements-dev.txt for tests and linting)
pip install -r requirements.txt -r requirements-ui.txt
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
OLLAMA_NUM_PARALLEL=4

# ─── Relational Database (Optional) ───
# Supports PostgreSQL, MSSQL, MySQL, Oracle, SQLite.
# Leave empty to use the sample SQLite database generated in data/ on first start.
DATABASE_URL=
DB_ALLOWED_TABLES=urunler,satislar,destek_talepleri
DB_MAX_ROWS=50
DB_QUERY_TIMEOUT_SECONDS=15

# ─── API & Security Settings ───
CORS_ORIGINS=http://localhost:8501,http://127.0.0.1:8501
MAX_UPLOAD_SIZE_MB=50
RATE_LIMIT_PER_MINUTE=30

# ─── Contextual Chunking & Retrieval ───
CHUNK_SIZE=600
CHUNK_OVERLAP=100
RERANKER_TOP_N=3
RAG_MIN_SIMILARITY=0.325
RAG_MIN_RERANKER_SCORE=0.005

# ─── Conversation Memory ───
CHAT_HISTORY_MAX_TURNS=20

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

Tests run against an isolated temporary data directory (see `tests/conftest.py`) and never touch your `data/` folder. LLM calls are stubbed, so tests do not need Ollama; the memory-profiling tests load the real embedding models and are skipped when the weights have not been downloaded.

---

## 🚀 Launching Services

### Backend (FastAPI Gateway):
```bash
# Recommended production launch (without --reload):
uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Or via the backward-compatible entry point:
uvicorn src.main:app --host 0.0.0.0 --port 8000
python -m src.main
```
* **Interactive Swagger Documentation:** `http://localhost:8000/docs`

> [!TIP]
> Avoid `--reload` outside development: every file change restarts the API and reloads the embedding and reranker models (~2 GB).

### Frontend (Streamlit Dashboard):
In a separate terminal window:
```bash
streamlit run ui/app.py
```
* **Web UI:** `http://localhost:8501`

> [!NOTE]
> **Initial Admin Credentials:**
> - **Username:** `admin`
> - **Password:** `admin123`
>
> The built-in default password must be changed at first login (the UI prompts for it; API clients use `POST /api/v1/auth/change-password`). Set `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` in `.env` to seed a different account.
