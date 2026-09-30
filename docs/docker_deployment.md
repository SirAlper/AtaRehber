# 🐳 Docker Deployment Guide

This guide details how to deploy `OpenLocalRagAgents` using **Docker** and **Docker Compose** for production and on-premise enterprise environments.

---

## 🏗️ Architecture Overview

The containerized deployment runs three services on an internal Docker bridge network, plus a one-shot `ollama-pull` job that downloads the LLM on the first start. For shared deployments, add the [HTTPS reverse proxy](#-https-reverse-proxy):

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
│  │     FastAPI + LangGraph + embedding/reranker models (PyTorch, CPU)         │  │
│  └───────────────────▲─────────────────────────────────────▲──────────────────┘  │
│                      │ (internal: 8000)                    │ (internal: 11434)   │
│  ┌───────────────────┴─────────────────┐  ┌────────────────┴──────────────────┐  │
│  │        rag_agents_frontend          │  │        rag_agents_ollama          │  │
│  │ Streamlit (Port 8501, light image)  │  │ LLM server (GPU via override),    │  │
│  │                                     │  │ internal network only             │  │
│  └─────────────────────────────────────┘  └───────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

* **Separate images:**
  * [`Dockerfile`](../Dockerfile) builds the **backend** in two stages. A builder stage compiles dependencies, and a `python:3.12-slim` runtime stage copies only the installed packages and the `src/` code. PyTorch is installed from the CPU wheel index; it only runs the embedding and reranker models (a CUDA build can be selected with the `TORCH_INDEX_URL` build argument).
  * The **LLM** runs in the official `ollama/ollama` image. Its models are stored in the `ollama_data` volume.
  * [`web/Dockerfile`](../web/Dockerfile) builds the **React web UI** (`web` service, port 8080): Node builds the static files, and an `nginx` image serves them and forwards `/api` and `/health` to the backend ([`web/deploy/nginx.conf`](../web/deploy/nginx.conf)), so the browser talks to one address. It runs next to the Streamlit UI during the transition.
  * [`Dockerfile.frontend`](../Dockerfile.frontend) builds a lightweight **Streamlit** image with only `streamlit` and `requests`, since the UI talks to the backend over HTTP and needs no ML stack.
* **Non-root containers:** Both images run as user `app` (uid/gid `1000`).
* **Zero-Bloat Image:** Retrieval model weights, vector indexes, documents and databases are mounted as host volumes, never baked into the image. `.env` files are excluded from the build context, so secrets never end up in image layers.
* **Data Persistence:** Rebuilding or recreating containers keeps your documents, audit log (`audit.db`), user accounts (`users.json`), JWT secret (`.jwt_secret`), conversation checkpoints (`multi_agent_conversations.db`), vector collections, and backups.

---

## 📋 Prerequisites

| Requirement | CPU Mode | NVIDIA GPU Mode |
| :--- | :--- | :--- |
| **Docker Engine** | Version 24.0+ | Version 24.0+ |
| **Docker Compose** | Compose v2.24+ (`docker compose`) | Compose v2.24+ (`docker compose`) |
| **NVIDIA Driver** | Not required (the LLM runs on CPU, slowly) | Version 525+ |
| **Container Toolkit** | Not required | [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) |

> [!NOTE]
> Compose v2.24 or newer is required for the optional `.env` file declaration (`env_file` with `required: false`).

---

## ⚡ Quickstart in 3 Steps

### Step 1: Provision Retrieval Models and Volume Directories
Download the embedding and reranker models to `./models` (requires the Python dependencies on the host, see [Installation](installation.md)). The LLM is pulled by the `ollama-pull` service on the first start.
```bash
python download_model.py
```

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

#### Option B: NVIDIA GPU Acceleration
Passes the host GPUs to the Ollama container, where the LLM runs. The embedding and reranker models stay on the backend's CPU:
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

#### Option C: Use an Ollama Already Running on the Host
Set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env` (Docker Desktop; on Linux use the host IP), pull the model on the host (`ollama pull qwen2.5:7b`), and start only the backend and frontend:
```bash
docker compose up -d --build --no-deps backend frontend
```

On the first start (options A and B), `ollama-pull` downloads `OLLAMA_MODEL` (~4.7 GB for `qwen2.5:7b`). The UI and API are available right away; questions work once the download has finished (`docker compose logs -f ollama-pull`).

### Step 3: Access Applications
* **Web UI (React):** `http://localhost:8080`
* **Streamlit Web UI (previous interface):** `http://localhost:8501`
* **FastAPI Swagger API:** `http://localhost:8000/docs`
* **Healthcheck API:** `http://localhost:8000/health` (unauthenticated liveness probe; the frontend starts once it reports healthy)

> [!NOTE]
> **Initial Admin Credentials:**
> - **Username:** `admin`
> - **Password:** `admin123`
>
> The built-in default password must be changed at first login (the UI prompts for it; API clients use `POST /api/v1/auth/change-password`). Set `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` in `.env` to seed a different account.

---

## 🔒 HTTPS Reverse Proxy

Use HTTPS for every deployment that other people access. `docker-compose.https.yml` adds an nginx proxy that terminates TLS on port 443 (port 80 redirects to it) and stops publishing the backend (8000) and UI (8501, 8080) ports on the host, so only the proxy is reachable from the network.

1. Put the certificate files in `deploy/certs/` (git-ignored):
   * `fullchain.pem`: the certificate followed by the intermediate certificates
   * `privkey.pem`: the private key

   Use the certificate issued by your IT department. For a test setup, create a self-signed one (browsers will show a warning):
   ```bash
   openssl req -x509 -nodes -newkey rsa:2048 -days 365 -subj "/CN=rag.example.edu" \
     -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem
   ```
2. Start with the override (add `-f docker-compose.gpu.yml` for GPU):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
   ```
3. Open `https://<server-name>/`.

What the proxy serves (`deploy/nginx/nginx.conf`):

| Path | Target | Notes |
| :--- | :--- | :--- |
| `/` | Streamlit UI | WebSocket upgrade enabled. To serve the React web UI instead, set `proxy_pass http://web;` in this block (the `web` upstream is already defined). |
| `/api/` | REST API | For API clients and portal integrations; every endpoint needs a JWT. Remove the block to serve only the UI. |
| `/health` | Backend liveness probe | |

The proxy also sets HSTS and other security headers, allows uploads up to 50 MB (keep in sync with `MAX_UPLOAD_SIZE_MB`), sets `REFRESH_COOKIE_SECURE=true` so the web UI's refresh token cookie is sent over HTTPS only, and passes the client IP to the backend (`FORWARDED_ALLOW_IPS=*` is safe only because the backend port is not published). If browser-based clients call the API directly, add the HTTPS origin to `CORS_ORIGINS`. CI validates the nginx configuration and checks that the override publishes no backend or UI ports.

---

## ⚙️ Custom Configuration (`.env`)

Copy `.env.example` to `.env` in the project root (next to `docker-compose.yml`). The backend service loads the whole file via `env_file`. The few variables with defaults in `docker-compose.yml` (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `RAG_DEVICE`, `CORS_ORIGINS`, …) use `${VAR:-default}` syntax, so values from `.env` always win.

```env
# ─── LLM (Ollama) ───
# The bundled ollama service; the ollama-pull job pulls OLLAMA_MODEL on the first start
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_CTX=4096
OLLAMA_NUM_PARALLEL=4

# ─── Authentication & RBAC ───
ADMIN_DEFAULT_USERNAME=admin
ADMIN_DEFAULT_PASSWORD=admin123
REQUIRE_DEFAULT_PASSWORD_CHANGE=true
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
# Web UI: send its refresh token cookie over HTTPS only (true behind HTTPS; the HTTPS compose sets it):
REFRESH_COOKIE_SECURE=false
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
RATE_LIMIT_READS_PER_MINUTE=300
# Guest access (visitors without an account, documents of GUEST_DOCUMENT_GROUP only):
GUEST_ACCESS_ENABLED=false
GUEST_DOCUMENT_GROUP=ziyaretci
GUEST_SESSION_MINUTES=120
GUEST_RATE_LIMIT_PER_MINUTE=10
MAX_QUEUED_QUERIES=10
LOG_LEVEL=INFO

# ─── Retrieval & Chunking ───
CHUNK_SIZE=600
CHUNK_OVERLAP=100
ARTICLE_CHUNK_SIZE=900
RAG_CANDIDATE_POOL=10
RERANKER_TOP_N=4
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

# Ollama service and the first-start model download
docker compose logs -f ollama ollama-pull
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

## 💾 Backups & Restore

**Creating backups.** `POST /api/v1/admin/backup` creates `backups/full_backup_<timestamp>/` with:
* `vector_db/`: the search index
* `data/`: documents, `users.json`, `audit.db`, `multi_agent_conversations.db`, the sample database. SQLite files are copied with the SQLite backup API, so backups taken while the server runs are consistent. The JWT secret is not included; after a restore users simply log in again.

For automatic backups set `BACKUP_INTERVAL_HOURS` (e.g. `24`) and `BACKUP_KEEP` (default `7`) in `.env`. Backups contain personal data (see [Data Protection](data_protection.md)): restrict access to `./backups` and copy it to a second location regularly.

**Restoring only the search index** (e.g. after a bad bulk upload): `POST /api/v1/admin/restore?backup_name=<name>`, then restart the backend.

**Full restore** (e.g. a new server):
1. Stop the services: `docker compose down`
2. Replace the contents of `./data` with `backups/<name>/data/` and the contents of `./vector_db` with `backups/<name>/vector_db/`. Keep the old directories until the restore is verified.
3. Start the services and log in. Check `GET /api/v1/admin/audit-verify`: the audit chain must be valid.

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

### 5. Questions Fail With "model is not pulled" or "not reachable":
Right after the first start the LLM may still be downloading. Follow `docker compose logs -f ollama-pull`; the job exits once the model is present. `GET /api/v1/stats` reports the current `llm_status`. To pull a different model into the bundled server: `docker compose exec ollama ollama pull <model>`.
