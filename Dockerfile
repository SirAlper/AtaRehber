# ==============================================================================
# OpenLocalRagAgents — Backend Production Dockerfile
# Multi-stage build for Python 3.11. PyTorch wheel variant is selected at build time:
#   CPU (default):  docker build .
#   CUDA 12.1:      docker build --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121 .
# ==============================================================================

# ────────────── Stage 1: Builder ──────────────
FROM python:3.11-slim AS builder

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install build tools needed for compiling Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch (CPU or CUDA wheels depending on TORCH_INDEX_URL)
RUN pip install --no-cache-dir torch --index-url ${TORCH_INDEX_URL}

# Install backend runtime dependencies only (no UI / dev tooling)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ────────────── Stage 2: Runtime ──────────────
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false \
    HOME=/home/app

WORKDIR /app

# Install only runtime OS dependencies (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user (uid 1000 matches the default host user for bind-mounted volumes)
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

# Copy installed Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create necessary persistent volume mount directories
RUN mkdir -p /app/data /app/models /app/vector_db /app/backups && chown -R app:app /app

# Copy project source code
COPY --chown=app:app src /app/src
COPY --chown=app:app download_model.py /app/

USER app

EXPOSE 8000

# Unauthenticated liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
