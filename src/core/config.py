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

# Rate Limiting (requests per minute per user). Questions, uploads, and other changes share
# RATE_LIMIT_PER_MINUTE; reads (GET) have their own budget, because the web UI reloads its panels (status,
# documents, requests, ...) with several GET requests on every click.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
RATE_LIMIT_READS_PER_MINUTE = int(os.getenv("RATE_LIMIT_READS_PER_MINUTE", "300"))

# Failed login attempts allowed per username within LOGIN_LOCKOUT_WINDOW_SECONDS before temporary lockout
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
LOGIN_LOCKOUT_WINDOW_SECONDS = int(os.getenv("LOGIN_LOCKOUT_WINDOW_SECONDS", "900"))

# ──────────────────────────── DATA PROTECTION & BACKUPS ────────────────────────────
# Store the text of user questions, answer previews, and feedback comments in the audit log. With false,
# the log keeps who asked, when, which agent answered, and how long it took (data minimization, KVKK/GDPR).
AUDIT_STORE_QUESTIONS = os.getenv("AUDIT_STORE_QUESTIONS", "true").lower() == "true"
# Delete audit entries / conversation sessions older than N days; 0 keeps them. Applied hourly.
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "0"))
SESSION_RETENTION_DAYS = int(os.getenv("SESSION_RETENTION_DAYS", "0"))
# Automatic full backups (vector index + data directory) every N hours; 0 disables them.
# Only the newest BACKUP_KEEP full backups are kept.
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "0"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))

# ──────────────────────────── LOGGING CONFIGURATION ────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", os.path.join(BASE_DIR, "app.log"))

# ──────────────────────────── AUTHENTICATION CONFIGURATION ────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
# Browser clients that send "X-Token-Transport: cookie" (the web UI) get the refresh token in an HttpOnly cookie
# instead of the response body, so a script injected into the page cannot read it. Set to true behind HTTPS.
REFRESH_COOKIE_SECURE = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"
ADMIN_DEFAULT_USERNAME = os.getenv("ADMIN_DEFAULT_USERNAME", "admin")
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
USERS_FILE_PATH = os.getenv("USERS_FILE_PATH", os.path.join(DOCS_PATH, "users.json"))
JWT_SECRET_FILE_PATH = os.path.join(DOCS_PATH, ".jwt_secret")
# Built-in insecure default password; accounts using it are forced to change it before using the API
INSECURE_DEFAULT_PASSWORD = "admin123"
REQUIRE_DEFAULT_PASSWORD_CHANGE = os.getenv("REQUIRE_DEFAULT_PASSWORD_CHANGE", "true").lower() == "true"
# Guest access: visitors ask questions without an account, only about documents shared with GUEST_DOCUMENT_GROUP
# (e.g. the open education faculty's regulations). Off by default. Documents shared with that group are also
# visible to every account.
GUEST_ACCESS_ENABLED = os.getenv("GUEST_ACCESS_ENABLED", "false").lower() == "true"
GUEST_DOCUMENT_GROUP = os.getenv("GUEST_DOCUMENT_GROUP", "ziyaretci").strip().lower()
GUEST_SESSION_MINUTES = int(os.getenv("GUEST_SESSION_MINUTES", "120"))
# Questions per minute of one guest session (accounts: RATE_LIMIT_PER_MINUTE)
GUEST_RATE_LIMIT_PER_MINUTE = int(os.getenv("GUEST_RATE_LIMIT_PER_MINUTE", "10"))

# ──────────────────────────── LLM (OLLAMA) ────────────────────────────
# The LLM is served by Ollama (https://ollama.com); no LLM weights are loaded in this process.
# Pull the model once before starting: `ollama pull qwen2.5:7b`
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
# Context window in tokens. Set explicitly because some Ollama versions default to 2048 and silently
# drop the start of longer prompts (system prompt and retrieved context).
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
# Model layers Ollama puts on the GPU; empty lets Ollama decide. Ollama keeps a safety margin and moves the last
# layers of qwen2.5:7b to the CPU on a 6 GB card; 99 forces all layers on the GPU (about 4x faster prompt
# processing there). Too high a value for the free VRAM makes loading the model fail.
OLLAMA_NUM_GPU = int(os.getenv("OLLAMA_NUM_GPU", "").strip() or -1)
# Maximum number of LLM requests the API sends to Ollama at once
OLLAMA_NUM_PARALLEL = int(os.getenv("OLLAMA_NUM_PARALLEL", "4"))
# Questions that may wait for a free slot; further questions are answered at once with HTTP 503 ("busy, try again
# shortly") instead of waiting until the web UI gives up after 180 s. Roughly 180 s / seconds per question minus
# OLLAMA_NUM_PARALLEL; 0 disables the limit.
MAX_QUEUED_QUERIES = int(os.getenv("MAX_QUEUED_QUERIES", "10"))
# Optional separate models per task; empty uses OLLAMA_MODEL (see src/agent/llm.py). A stronger grader catches
# more wrong answers, a small router model keeps routing fast. Every configured model must be pulled.
OLLAMA_ROUTER_MODEL = os.getenv("OLLAMA_ROUTER_MODEL", "").strip()
OLLAMA_GRADER_MODEL = os.getenv("OLLAMA_GRADER_MODEL", "").strip()
# Answers of doc_agent to first questions (no conversation yet) are reused for the same question and document
# access until the documents change or ANSWER_CACHE_MINUTES pass; 0 turns the cache off
ANSWER_CACHE_SIZE = int(os.getenv("ANSWER_CACHE_SIZE", "256"))
ANSWER_CACHE_MINUTES = int(os.getenv("ANSWER_CACHE_MINUTES", "1440"))
# Answer check (src/agent/verification.py): a second look when the grader rejects an answer; every number of the
# answer must be in the grader's quotes; an answer relying only on a transitional article is sent back once
GRADER_SECOND_OPINION = os.getenv("GRADER_SECOND_OPINION", "true").lower() == "true"
GRADER_NUMBER_CHECK = os.getenv("GRADER_NUMBER_CHECK", "true").lower() == "true"
GRADER_TRANSITIONAL_CHECK = os.getenv("GRADER_TRANSITIONAL_CHECK", "true").lower() == "true"
# doc_agent copies the sentences its answer relies on before answering (EVIDENCE / ANSWER lines)
ANSWER_EVIDENCE_FIRST = os.getenv("ANSWER_EVIDENCE_FIRST", "false").lower() == "true"
# doc_agent may call the calculator and date tools (deadlines, averages) while answering
DOC_AGENT_TOOLS = os.getenv("DOC_AGENT_TOOLS", "false").lower() == "true"
# How doc_agent checks its answers: "quotes" makes the grader back every fact with a sentence copied from the
# documents and verifies the copies in code; "simple" asks only for yes/no (faster, less reliable).
GRADER_MODE = os.getenv("GRADER_MODE", "quotes").strip().lower()

# ──────────────────────────── ORGANIZATION ────────────────────────────
# Name used in prompts and fixed answers, e.g. "Example University". Empty: "the organization".
ORGANIZATION_NAME = os.getenv("ORGANIZATION_NAME", "").strip()

# ──────────────────────────── MULTI-AGENT WORKFLOW ────────────────────────────
# Maximum number of agent steps the supervisor may plan for one question (composite questions)
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "3"))
# Maximum number of times per question a failing agent may hand the task to another agent
MAX_AGENT_HANDOFFS = int(os.getenv("MAX_AGENT_HANDOFFS", "1"))
# Ask one question back when a question can mean things with different answers ("İzin süresi ne kadar?")
CLARIFY_QUESTIONS = os.getenv("CLARIFY_QUESTIONS", "true").lower() == "true"
# Seconds one agent step may take; a slower step is answered with "could not be completed in time" and the other
# steps still count (0 = no limit)
AGENT_STEP_TIMEOUT_SECONDS = int(os.getenv("AGENT_STEP_TIMEOUT_SECONDS", "180"))

# ──────────────────────────── SERVICE REQUESTS & NOTIFICATIONS ────────────────────────────
# Categories the request agent files requests under
REQUEST_CATEGORIES = [
    c.strip().lower()
    for c in os.getenv("REQUEST_CATEGORIES", "it_support,facilities,academic,administrative,other").split(",")
    if c.strip()
]
# Who is e-mailed about new requests: "category=address,...", "default=address" for the rest. Empty: no e-mail.
REQUEST_NOTIFY_EMAILS = {
    key.strip().lower(): value.strip()
    for key, _, value in (
        item.partition("=") for item in os.getenv("REQUEST_NOTIFY_EMAILS", "").split(",") if "=" in item
    )
    if key.strip() and value.strip()
}
# Put the requester, title, and description into notification e-mails. With false the e-mail only says that
# request #N of a category was filed, and staff read the details in the application (data minimization).
REQUEST_NOTIFY_INCLUDE_DETAILS = os.getenv("REQUEST_NOTIFY_INCLUDE_DETAILS", "true").lower() == "true"
# Delete resolved, rejected, and cancelled requests older than N days; 0 keeps them. Applied hourly.
REQUEST_RETENTION_DAYS = int(os.getenv("REQUEST_RETENTION_DAYS", "0"))
# Internal mail server for request notifications. Empty SMTP_HOST disables e-mail.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))

# ──────────────────────────── RETRIEVAL MODELS (LOCAL) ────────────────────────────
# Embedding and reranker models run in this process (Ollama has no reranking support).
LOCAL_EMBEDDING_PATH = os.path.join(MODELS_DIR, "bge-m3")
LOCAL_RERANKER_PATH = os.path.join(MODELS_DIR, "bge-reranker-v2-m3")

# Load from local folder if exists, otherwise fallback to HuggingFace Hub model ID
EMBEDDING_MODEL_NAME = LOCAL_EMBEDDING_PATH if os.path.exists(LOCAL_EMBEDDING_PATH) else "BAAI/bge-m3"
RERANKER_MODEL_NAME = LOCAL_RERANKER_PATH if os.path.exists(LOCAL_RERANKER_PATH) else "BAAI/bge-reranker-v2-m3"

# Candidates the vector search hands to the cross-encoder per question
RAG_CANDIDATE_POOL = int(os.getenv("RAG_CANDIDATE_POOL", "10"))
# Number of top candidate chunks to pass to LLM after Cross-Encoder reranking. 4 instead of 3 lets an answer
# that needs a neighbouring piece of a long article (a list of penalties) see it; no loss on the demo set (evals)
RERANKER_TOP_N = int(os.getenv("RERANKER_TOP_N", "4"))
# Minimum cosine similarity for a vector search candidate to reach the reranker
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.325"))
# Minimum cross-encoder relevance score (0-1) for a chunk to be used as context. The bi-encoder similarity
# cannot tell off-topic questions apart; the reranker can (see docs/evaluation.md). 0 disables the check.
RAG_MIN_RERANKER_SCORE = float(os.getenv("RAG_MIN_RERANKER_SCORE", "0.005"))

# ──────────────────────────── CONVERSATION MEMORY ────────────────────────────
MULTI_AGENT_CONVERSATIONS_DB = os.path.join(DOCS_PATH, "multi_agent_conversations.db")
REQUESTS_DB = os.path.join(DOCS_PATH, "requests.db")
# Which user groups may search each restricted document (documents not listed are visible to everyone)
DOCUMENT_ACCESS_FILE = os.path.join(DOCS_PATH, "document_access.json")
# Agents defined by admins in the web UI (name, purpose, instructions, tools)
CUSTOM_AGENTS_FILE = os.path.join(DOCS_PATH, "custom_agents.json")
# Staff answers to questions the documents did not answer; searched like a document (see src/services/faq.py)
FAQ_FILE = os.path.join(DOCS_PATH, "faq.json")
CHAT_HISTORY_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "20"))

# ──────────────────────────── CHUNKING CONFIGURATION ────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
# Laws and regulations are split by article; articles longer than this are split further
ARTICLE_CHUNK_SIZE = int(os.getenv("ARTICLE_CHUNK_SIZE", "900"))

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Enable offline mode only if the local retrieval models exist and online download flag is not set
ALL_LOCAL_MODELS_EXIST = os.path.exists(LOCAL_EMBEDDING_PATH) and os.path.exists(LOCAL_RERANKER_PATH)
if ALL_LOCAL_MODELS_EXIST and os.getenv("ALLOW_ONLINE_HF", "0") != "1":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Embedding and Reranker Device:
# Configured by default to CPU to keep full GPU VRAM available for Ollama
RAG_DEVICE = os.getenv("RAG_DEVICE", "cpu")

# ──────────────────────────── DATABASE CONNECTION (OPTIONAL) ────────────────────────────
# Example connections:
# - PostgreSQL: "postgresql+psycopg2://user:pass@localhost:5432/enterprise_db"
# - MSSQL: "mssql+pyodbc://user:pass@host:1433/db?driver=ODBC+Driver+17+for+SQL+Server"
# - MySQL: "mysql+pymysql://user:pass@localhost:3306/db"
# - SQLite: "sqlite:///./data/sample_enterprise.db"
# If left empty, the demo database below is used (SAMPLE_DB_ENABLED=true) or database features are disabled.
SAMPLE_DB_PATH = os.path.join(DOCS_PATH, "sample_enterprise.db")
DEFAULT_SQLITE_URL = f"sqlite:///{SAMPLE_DB_PATH}"
# Demo database with fictitious products, sales, and support tickets. Disable it in real deployments without a
# database: otherwise questions such as "how many ..." can be answered from the demo data.
SAMPLE_DB_ENABLED = os.getenv("SAMPLE_DB_ENABLED", "true").lower() == "true"

DATABASE_URL = os.getenv(
    "DATABASE_URL", DEFAULT_SQLITE_URL if SAMPLE_DB_ENABLED and os.path.exists(SAMPLE_DB_PATH) else ""
)
DB_ALLOWED_TABLES = [t.strip() for t in os.getenv("DB_ALLOWED_TABLES", "").split(",") if t.strip()]
DB_MAX_ROWS = int(os.getenv("DB_MAX_ROWS", "50"))
DB_QUERY_TIMEOUT_SECONDS = int(os.getenv("DB_QUERY_TIMEOUT_SECONDS", "15"))
