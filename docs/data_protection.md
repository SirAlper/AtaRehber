# 🔏 Data Protection (KVKK / GDPR)

This page is for data protection officers and IT teams reviewing a deployment. It lists which personal data the system stores, where, for how long, and which settings control it. It describes the software; the legal assessment (legal basis, privacy notice, records of processing) remains the operator's responsibility.

---

## 🏠 Where Processing Happens

Everything runs on the operator's own servers: the API, the embedding and reranker models, the vector index, and the LLM (Ollama). The software makes no calls to external services at runtime; the assistant has no internet access. The only outgoing connection is optional: request notification e-mails through the operator's own mail server (`SMTP_HOST`, off by default). Model weights are downloaded once during installation (`download_model.py`, `ollama pull`); afterwards the system can run without internet access.

---

## 🗂️ Personal Data Stored

| Location | Contents | Personal data | Retention |
| :--- | :--- | :--- | :--- |
| `data/users.json` | User accounts | Username, role, user groups, bcrypt password hash, account status | Until the account is deleted |
| `data/audit.db` | Audit trail | Username, role, client IP, timestamp, action, **question text**, **answer preview (first 500 characters)**, **feedback comments**, names of cited documents | `AUDIT_RETENTION_DAYS` (default: kept) |
| `data/multi_agent_conversations.db` | Conversation memory for follow-up questions | Username (in the session ID), questions and answers of each session, a drafted service request awaiting confirmation | `SESSION_RETENTION_DAYS` (default: kept) |
| `data/requests.db` | Service requests filed through the chat or the form | Requester username, title, description (the user's own words), status, staff notes, who changed it | `REQUEST_RETENTION_DAYS` for closed requests (default: kept) |
| Notification e-mails | Sent to the unit configured per category | Request number and category; with `REQUEST_NOTIFY_INCLUDE_DETAILS=true` also the requester, title, and description | The mail system's own retention |
| `data/document_access.json` | Which user groups may search each restricted document | None (file names and group names) | Until the document is deleted or made public |
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
| `REQUEST_RETENTION_DAYS` | `0` (keep) | Resolved, rejected, and cancelled service requests last changed longer ago than this are deleted hourly. Open requests are kept. |
| `SMTP_HOST` / `REQUEST_NOTIFY_EMAILS` | empty (no e-mail) | Request notifications through the organization's mail server, only to the configured addresses. |
| `REQUEST_NOTIFY_INCLUDE_DETAILS` | `true` | With `false`, e-mails only say that request #N of a category was filed; staff read the details in the application (data minimization). |
| `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP` | `0` (off) / `7` | Automatic full backups and how many are kept. Backups contain personal data; store them with restricted access. |
| `LOG_LEVEL` | `INFO` | Do not use `DEBUG` in production: it writes question text to the application log. |

Retention and backups run inside the API once at startup and then every hour. `POST /api/v1/admin/maintenance/run` runs them immediately.

---

## 🔐 Access Control

* Only `admin` accounts can read the audit log (`/api/v1/admin/audit-logs`) and create or restore backups.
* Conversation memory is separated per user: a session ID is always combined with the username, so users cannot read each other's conversations.
* **Document access groups:** documents can be restricted to user groups when they are uploaded or later (`PUT /api/v1/documents/{filename}/access`). Viewers only receive answers, sources, and document lists from public documents and documents shared with their groups; the filter is applied inside the vector search, before anything reaches the model. Admins and editors see all documents. Documents uploaded without groups are visible to every user.
* **Service requests:** users see only their own requests; staff (`admin`, `editor`) see all of them.
* In the Docker HTTPS setup (`docker-compose.https.yml`), traffic is encrypted and only the proxy is reachable from the network.

---

## ⚠️ Current Limitations

* **Deleting a user account does not delete their audit entries or conversations.** Until a per-user erasure function exists, remove them with the retention settings or manually by an administrator.
* **No encryption at rest.** Use disk or volume encryption on the server if the documents or questions are sensitive.
* **Group membership is managed in the application** (`PUT`/`PATCH` user groups by an admin); it is not synchronized with a directory service such as LDAP or Active Directory yet.
* **Notification e-mails leave the application's retention control.** Use `REQUEST_NOTIFY_INCLUDE_DETAILS=false` if request texts may contain sensitive data, and mention the e-mail in the privacy notice if it is enabled.

---

## ✅ Recommended Settings for a Pilot

```env
AUDIT_STORE_QUESTIONS=false      # or true for a limited period, if answer quality has to be reviewed
AUDIT_RETENTION_DAYS=180
SESSION_RETENTION_DAYS=30
REQUEST_RETENTION_DAYS=365
REQUEST_NOTIFY_INCLUDE_DETAILS=false   # if e-mail notifications are enabled
SAMPLE_DB_ENABLED=false                # no demo data in a real deployment
BACKUP_INTERVAL_HOURS=24
BACKUP_KEEP=7
LOG_LEVEL=INFO
```

Adjust the periods to the institution's retention policy and document them in the privacy notice.
