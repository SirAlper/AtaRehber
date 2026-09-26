import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_DIR = os.path.join(BASE_DIR, "models")
VECTOR_DB_PATH = os.path.join(BASE_DIR, "vector_db")
DOCS_PATH = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))

# ──────────────────────────── API & SECURITY CONFIGURATION ────────────────────────────
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501").split(",")
    if origin.strip()
]
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt"}

# Rate Limiting (requests per minute per user)
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

# Failed login attempts allowed per username within LOGIN_LOCKOUT_WINDOW_SECONDS before temporary lockout
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
LOGIN_LOCKOUT_WINDOW_SECONDS = int(os.getenv("LOGIN_LOCKOUT_WINDOW_SECONDS", "900"))

# ──────────────────────────── LOGGING CONFIGURATION ────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", os.path.join(BASE_DIR, "app.log"))

# ──────────────────────────── AUTHENTICATION CONFIGURATION ────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
ADMIN_DEFAULT_USERNAME = os.getenv("ADMIN_DEFAULT_USERNAME", "admin")
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
USERS_FILE_PATH = os.getenv("USERS_FILE_PATH", os.path.join(DOCS_PATH, "users.json"))
JWT_SECRET_FILE_PATH = os.path.join(DOCS_PATH, ".jwt_secret")
# Built-in insecure default password; accounts using it are forced to change it before using the API
INSECURE_DEFAULT_PASSWORD = "admin123"
REQUIRE_DEFAULT_PASSWORD_CHANGE = os.getenv("REQUIRE_DEFAULT_PASSWORD_CHANGE", "true").lower() == "true"

# ──────────────────────────── LLM & SERVING CONFIGURATION ────────────────────────────
# Backend: "huggingface" (in-process) or "ollama" (external high-concurrency server)
LLM_BACKEND = os.getenv("LLM_BACKEND", "huggingface").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_NUM_PARALLEL = int(os.getenv("OLLAMA_NUM_PARALLEL", "4"))

LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
LLM_MODEL_DIR = os.getenv("LLM_MODEL_DIR", "qwen2.5-1.5b")
LOCAL_LLM_PATH = os.path.join(MODELS_DIR, LLM_MODEL_DIR)
LOCAL_EMBEDDING_PATH = os.path.join(MODELS_DIR, "bge-m3")
LOCAL_RERANKER_PATH = os.path.join(MODELS_DIR, "bge-reranker-v2-m3")

# Load from local folder if exists, otherwise fallback to HuggingFace Hub model ID
LLM_MODEL_NAME = LOCAL_LLM_PATH if os.path.exists(LOCAL_LLM_PATH) else LLM_MODEL_ID
EMBEDDING_MODEL_NAME = LOCAL_EMBEDDING_PATH if os.path.exists(LOCAL_EMBEDDING_PATH) else "BAAI/bge-m3"
RERANKER_MODEL_NAME = LOCAL_RERANKER_PATH if os.path.exists(LOCAL_RERANKER_PATH) else "BAAI/bge-reranker-v2-m3"

# Number of top candidate chunks to pass to LLM after Cross-Encoder reranking
RERANKER_TOP_N = int(os.getenv("RERANKER_TOP_N", "3"))
# Minimum cosine similarity for a vector search candidate to reach the reranker
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.325"))

# ──────────────────────────── CONVERSATION MEMORY ────────────────────────────
MULTI_AGENT_CONVERSATIONS_DB = os.path.join(DOCS_PATH, "multi_agent_conversations.db")
CHAT_HISTORY_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "20"))

# ──────────────────────────── CHUNKING CONFIGURATION ────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Enable offline mode only if all local models exist and online download flag is not set
ALL_LOCAL_MODELS_EXIST = (
    os.path.exists(LOCAL_LLM_PATH) and os.path.exists(LOCAL_EMBEDDING_PATH) and os.path.exists(LOCAL_RERANKER_PATH)
)
if ALL_LOCAL_MODELS_EXIST and os.getenv("ALLOW_ONLINE_HF", "0") != "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

# PyTorch 4-bit quantization setting (1.5B model in BF16 consumes only ~2.8GB VRAM)
USE_4BIT_QUANTIZATION = False

# Embedding and Reranker Device:
# Configured by default to CPU to keep full GPU VRAM available for the LLM
RAG_DEVICE = os.getenv("RAG_DEVICE", "cpu")

# ──────────────────────────── DATABASE CONNECTION (OPTIONAL) ────────────────────────────
# Example connections:
# - PostgreSQL: "postgresql+psycopg2://user:pass@localhost:5432/enterprise_db"
# - MSSQL: "mssql+pyodbc://user:pass@host:1433/db?driver=ODBC+Driver+17+for+SQL+Server"
# - MySQL: "mysql+pymysql://user:pass@localhost:3306/db"
# - SQLite: "sqlite:///./data/sample_enterprise.db"
# If left empty, database features are disabled and the system operates purely on file RAG.
SAMPLE_DB_PATH = os.path.join(DOCS_PATH, "sample_enterprise.db")
DEFAULT_SQLITE_URL = f"sqlite:///{SAMPLE_DB_PATH}"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL if os.path.exists(SAMPLE_DB_PATH) else "")
DB_ALLOWED_TABLES = [t.strip() for t in os.getenv("DB_ALLOWED_TABLES", "").split(",") if t.strip()]
DB_MAX_ROWS = int(os.getenv("DB_MAX_ROWS", "50"))
DB_QUERY_TIMEOUT_SECONDS = int(os.getenv("DB_QUERY_TIMEOUT_SECONDS", "15"))
