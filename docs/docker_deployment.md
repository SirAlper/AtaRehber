# 🐳 Docker Deployment Guide

This guide details how to deploy `OpenLocalRagAgents` using **Docker** and **Docker Compose** for production and on-premise enterprise environments.

---

## 🏗️ Architecture Overview

The containerized deployment supports up to three decoupled services communicating over an internal Docker bridge network:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                  Host Machine                                    │
│                                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ./models/    │  │ ./data/      │  │ ./vector_db/ │  │ ./backups/           │  │
│  │ (weights)    │  │ (DBs, audit, │  │ (ChromaDB)   │  │ (vector DB snapshots │  │
│  │              │  │  users)      │  │              │  │  & staged restores)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │ (volume)        │ (volume)        │ (volume)            │ (volume)     │
│         ▼                 ▼                 ▼                     ▼              │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │                   rag_agents_backend (Port 8000)                           │  │
│  │          FastAPI + LangGraph + PyTorch (CPU default / CUDA)                │  │
│  └───────────────────▲─────────────────────────────────────▲──────────────────┘  │
│                      │ (internal: 8000)                    │ (internal: 11434)   │
│  ┌───────────────────┴─────────────────┐  ┌────────────────┴──────────────────┐  │
│  │        rag_agents_frontend          │  │        rag_agents_ollama          │  │
│  │ Streamlit (Port 8501, light image)  │  │ (optional profile: ollama,        │  │
│  │                                     │  │  bound to 127.0.0.1:11434)        │  │
│  └─────────────────────────────────────┘  └───────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

* **Separate images:**
  * [`Dockerfile`](../Dockerfile) builds the **backend** in two stages. A builder stage compiles dependencies, and a `python:3.12-slim` runtime stage copies only the installed packages and the `src/` code. PyTorch is installed from the CPU wheel index by default; the GPU override builds with CUDA 12.1 wheels (`TORCH_INDEX_URL` build argument).
  * [`Dockerfile.frontend`](../Dockerfile.frontend) builds a lightweight **Streamlit** image with only `streamlit` and `requests`, since the UI talks to the backend over HTTP and needs no ML stack.
* **Non-root containers:** Both images run as user `app` (uid/gid `1000`).
* **Zero-Bloat Image:** Model weights, vector indexes, documents and databases are mounted as host volumes, never baked into the image. `.env` files are excluded from the build context, so secrets never end up in image layers.
* **Data Persistence:** Rebuilding or recreating containers keeps your documents, audit log (`audit.db`), user accounts (`users.json`), JWT secret (`.jwt_secret`), conversation checkpoints (`multi_agent_conversations.db`), vector collections, and backups.

---

## 📋 Prerequisites

| Requirement | CPU Mode | NVIDIA GPU Mode |
| :--- | :--- | :--- |
| **Docker Engine** | Version 24.0+ | Version 24.0+ |
| **Docker Compose** | Compose v2.24+ (`docker compose`) | Compose v2.24+ (`docker compose`) |
| **NVIDIA Driver** | Not required | Version 525+ |
| **Container Toolkit** | Not required | [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) |

> [!NOTE]
> Compose v2.24 or newer is required for the optional `.env` file declaration (`env_file` with `required: false`).

---

## ⚡ Quickstart in 3 Steps

### Step 1: Provision Local Models and Volume Directories
Before starting the containers in HuggingFace mode, download the local models to `./models` (requires the Python dependencies on the host, see [Installation](installation.md)):
```bash
python download_model.py
```
*(If you use the Ollama profile exclusively, HuggingFace LLM weights are optional; the embedding and reranker models are still required.)*

The containers run as uid `1000`. On Linux, create the volume directories up front so they are owned by your user (Docker would otherwise create missing ones as `root`, and the backend could not write to them):
```bash
mkdir -p data vector_db backups models
# If your user is not uid 1000:
sudo chown -R 1000:1000 data vector_db backups
```

### Step 2: Launch the Services

#### Option A: CPU Execution (Default)
```bash
docker compose up -d --build
```

#### Option B: NVIDIA GPU Acceleration (CUDA Passthrough)
Builds the backend with CUDA 12.1 PyTorch wheels, sets `RAG_DEVICE=cuda`, and passes host GPUs to the backend container:
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

#### Option C: With Ollama High-Concurrency Serving Profile
Starts the bundled Ollama server alongside the backend and frontend. Set `LLM_BACKEND=ollama` in `.env` so the backend uses it, then pull the model once:
```bash
docker compose --profile ollama up -d --build
docker compose exec ollama ollama pull qwen2.5:7b
```

### Step 3: Access Applications
* **Streamlit Web UI:** `http://localhost:8501`
* **FastAPI Swagger API:** `http://localhost:8000/docs`
* **Healthcheck API:** `http://localhost:8000/health` (unauthenticated liveness probe; the frontend starts once it reports healthy)

> [!NOTE]
> **Initial Admin Credentials:**
> - **Username:** `admin`
> - **Password:** `admin123`
>
> The built-in default password must be changed at first login (the UI prompts for it; API clients use `POST /api/v1/auth/change-password`). Set `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` in `.env` to seed a different account.

---

## ⚙️ Custom Configuration (`.env`)

Copy `.env.example` to `.env` in the project root (next to `docker-compose.yml`). The backend service loads the whole file via `env_file`. The few variables with defaults in `docker-compose.yml` (`LLM_BACKEND`, `RAG_DEVICE`, `CORS_ORIGINS`, …) use `${VAR:-default}` syntax, so values from `.env` always win.

```env
# ─── LLM Serving Backend ───
# Options: "huggingface" (local in-process) or "ollama" (external server)
LLM_BACKEND=huggingface
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_PARALLEL=4

# ─── Authentication & RBAC ───
ADMIN_DEFAULT_USERNAME=admin
ADMIN_DEFAULT_PASSWORD=admin123
REQUIRE_DEFAULT_PASSWORD_CHANGE=true
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_WINDOW_SECONDS=900
# Optional custom HMAC secret (randomly generated and saved to data/.jwt_secret if empty):
# JWT_SECRET_KEY=your_custom_secret_key

# ─── Password Strength Policy ───
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=true
PASSWORD_REQUIRE_LOWERCASE=true
PASSWORD_REQUIRE_DIGIT=true
PASSWORD_REQUIRE_SPECIAL=false

# ─── Relational Database (Optional) ───
# Leave empty to use the auto-generated sample SQLite database in ./data
DATABASE_URL=
DB_ALLOWED_TABLES=urunler,satislar,destek_talepleri
DB_MAX_ROWS=50
DB_QUERY_TIMEOUT_SECONDS=15

# ─── API & Security ───
CORS_ORIGINS=http://localhost:8501,http://127.0.0.1:8501,http://frontend:8501
MAX_UPLOAD_SIZE_MB=50
RATE_LIMIT_PER_MINUTE=30
LOG_LEVEL=INFO

# ─── Retrieval & Chunking ───
CHUNK_SIZE=600
CHUNK_OVERLAP=100
RERANKER_TOP_N=3
RAG_MIN_SIMILARITY=0.325
RAG_MIN_RERANKER_SCORE=0.005
```

See [`.env.example`](../.env.example) for the complete list of settings.

> [!IMPORTANT]
> Inside the container, host services are not reachable via `localhost`. For an external database or Ollama running on the host, use `host.docker.internal` (Docker Desktop) or the host's IP address in `DATABASE_URL` / `OLLAMA_BASE_URL`.

---

## 🔍 Useful Operational Commands

### View Logs in Real-time:
```bash
# All services
docker compose logs -f

# Backend API only
docker compose logs -f backend

# Frontend UI only
docker compose logs -f frontend

# Ollama service only (if profile active)
docker compose logs -f ollama
```

### Inspect Container Health:
```bash
docker compose ps
```

### Apply a Staged Vector Database Restore:
`POST /api/v1/admin/restore` only stages the snapshot (in `./backups/.restore_pending`). Restart the backend to apply it:
```bash
docker compose restart backend
```

### Stop Services:
```bash
docker compose down
```

### Stop and Remove Volumes (Caution: Clears Ollama cache):
```bash
docker compose down -v
```
*(Host bind mounts such as `./data` and `./vector_db` are not deleted by this command.)*

---

## 🛠️ Troubleshooting

### 1. NVIDIA Container Toolkit Verification:
To confirm GPU passthrough is functional on your Docker host:
```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

### 2. Port Conflicts:
If port `8000` or `8501` is already in use on your host machine, update the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"  # Changes host backend port to 8080
```

### 3. `PermissionError` on `/app/data`, `/app/vector_db`, or `/app/backups`:
The backend runs as uid `1000` and must be able to write to the mounted directories. Fix ownership on the host:
```bash
sudo chown -R 1000:1000 data vector_db backups
```

### 4. Frontend Never Starts:
The frontend waits for the backend healthcheck (`/health`). Loading models can take a few minutes on first start (`start_period: 120s`). Check `docker compose logs -f backend` for model loading or download errors, for example missing weights in `./models`.
