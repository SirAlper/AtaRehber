# 🔏 Data Protection (KVKK / GDPR)

This page is for data protection officers and IT teams reviewing a deployment. It lists which personal data the system stores, where, for how long, and which settings control it. It describes the software; the legal assessment (legal basis, privacy notice, records of processing) remains the operator's responsibility.

---

## 🏠 Where Processing Happens

Everything runs on the operator's own servers: the API, the embedding and reranker models, the vector index, and the LLM (Ollama). The software makes no calls to external services at runtime. Model weights are downloaded once during installation (`download_model.py`, `ollama pull`); afterwards the system can run without internet access.

---

## 🗂️ Personal Data Stored

| Location | Contents | Personal data | Retention |
| :--- | :--- | :--- | :--- |
| `data/users.json` | User accounts | Username, role, bcrypt password hash, account status | Until the account is deleted |
| `data/audit.db` | Audit trail | Username, role, client IP, timestamp, action, **question text**, **answer preview (first 500 characters)**, **feedback comments**, names of cited documents | `AUDIT_RETENTION_DAYS` (default: kept) |
| `data/multi_agent_conversations.db` | Conversation memory for follow-up questions | Username (in the session ID), questions and answers of each session | `SESSION_RETENTION_DAYS` (default: kept) |
| `app.log` (`LOG_FILE`) | Application log | Usernames, session IDs, question length. Question text only at `LOG_LEVEL=DEBUG` | Rotated: 5 files of 10 MB |
| `data/` documents and `vector_db/` | Uploaded documents and their search index | Whatever the uploaded documents contain | Until the document is deleted |
| `backups/` | Full backups | Copies of all of the above (except the JWT secret) | `BACKUP_KEEP` newest full backups |

Questions typed by users can contain personal data about themselves or others (names, student numbers, health information). Treat the audit log and conversation memory accordingly.

---

## ⚙️ Settings

| Setting | Default | Effect |
| :--- | :--- | :--- |
| `AUDIT_STORE_QUESTIONS` | `true` | With `false`, the audit log records who asked, when, which agent answered, and how long it took, but not the question text, the answer preview, or feedback comments. |
| `AUDIT_RETENTION_DAYS` | `0` (keep) | Audit entries older than this are deleted hourly. The hash chain stays verifiable: the hash of the newest deleted entry is kept as the chain anchor, and every purge is itself recorded as a `retention_purge` entry. |
| `SESSION_RETENTION_DAYS` | `0` (keep) | Conversations inactive for longer than this are deleted hourly. |
| `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP` | `0` (off) / `7` | Automatic full backups and how many are kept. Backups contain personal data; store them with restricted access. |
| `LOG_LEVEL` | `INFO` | Do not use `DEBUG` in production: it writes question text to the application log. |

Retention and backups run inside the API once at startup and then every hour. `POST /api/v1/admin/maintenance/run` runs them immediately.

---

## 🔐 Access Control

* Only `admin` accounts can read the audit log (`/api/v1/admin/audit-logs`) and create or restore backups.
* Conversation memory is separated per user: a session ID is always combined with the username, so users cannot read each other's conversations.
* All users can query all indexed documents; there is no document-level access control yet. Only upload documents that every user of the system may see.
* In the Docker HTTPS setup (`docker-compose.https.yml`), traffic is encrypted and only the proxy is reachable from the network.

---

## ⚠️ Current Limitations

* **Deleting a user account does not delete their audit entries or conversations.** Until a per-user erasure function exists, remove them with the retention settings or manually by an administrator.
* **No encryption at rest.** Use disk or volume encryption on the server if the documents or questions are sensitive.
* **Document-level permissions are missing** (see above).

---

## ✅ Recommended Settings for a Pilot

```env
AUDIT_STORE_QUESTIONS=false      # or true for a limited period, if answer quality has to be reviewed
AUDIT_RETENTION_DAYS=180
SESSION_RETENTION_DAYS=30
BACKUP_INTERVAL_HOURS=24
BACKUP_KEEP=7
LOG_LEVEL=INFO
```

Adjust the periods to the institution's retention policy and document them in the privacy notice.
