# 🚀 What's New in AtaRehber

This document provides a comprehensive log of new features, architectural upgrades, system components, API endpoints, and user experience enhancements introduced in **AtaRehber**.

---

## 🧭 Unreleased

### Answer check that does not depend on how well a model copies
Measured on the 127 university questions, `qwen2.5:14b` scored below `qwen2.5:7b` (documents 83.8% against 91.4%), and half of the loss came from the answer check, not from the answers: the larger model garbled Turkish letters in the quotes it copied, so they were not found in the documents. New settings; the first three keep the earlier behaviour by default until both models are measured with them:
* **`GRADER_MODE=sentences`:** the sentences of the retrieved passages are numbered and the grader gives the numbers of the ones that state the facts; the evidence shown with the answer is then the documents' own text, and the grader's reply is shorter.
* **`GRADER_STRICT_QUOTES=false`** (with `GRADER_MODE=quotes`): a quote that is not in the documents is left out instead of failing the answer, as long as another quote is found.
* **`GRADER_RELEVANCE_CHECK=true`:** the grader also says whether the answer gives what the question asks for; the general form of the quantity check (`GRADER_QUANTITY_CHECK`), which only knows "how many" questions and rejected a correct answer in that measurement.
* **`ANSWER_SCRIPT_CHECK`** (on): an answer with letters of a script the documents do not use (Chinese in the middle of a Turkish answer) is written again once.

### Measuring several models
* **Reply length is a setting:** `OLLAMA_NUM_PREDICT` (default 512, as before) instead of a fixed value in the code.
* **Reports say which models and checks ran:** the `config` block of an evaluation report now records the router and grader models, the reply length, and the answer-check switches (`GRADER_*`, `ANSWER_EVIDENCE_FIRST`, `DOC_AGENT_TOOLS`), so two runs can be told apart later.
* **Kaggle notebook:** `evals/kaggle_eval.ipynb` runs the evaluation once per model of `MODELS` and shows the reports side by side; `GRADER_MODEL` lets one model check the answers of another, `EXTRA_ENV` sets any other setting.

### Fixed: documents still being indexed, and sources under "not in the documents"
* **A document being indexed is shown as such:** an uploaded file is on disk minutes before its chunks are in the index (a long law takes several minutes on the CPU), and the document list showed it like a ready one. The list now marks it "Indexing… not searchable yet" (`indexing` in `GET /api/v1/documents`) and reloads until it is done; a file whose indexing failed is marked "Not indexed; upload it again".
* **Answers that talk about the topic instead of answering:** "Yıllık izin hakkı kaç gündür?" got "leave is used while teaching is suspended (Madde 64)" as a verified answer, because everything it said is in the law, although the law states no number of days. An answer to a question that asks for a quantity ("kaç gün", "ne kadar", "how many") must now state one or say that there is none; otherwise it is sent back once, and if it still states none, the answer is "not in the documents" (`GRADER_QUANTITY_CHECK`). None of the 48 correct answers to quantity questions in the university answer-check dataset is affected; the end-to-end evaluation has not been re-run.
* **No sources under "not in the documents":** when the model read passages and found that they do not answer the question, the answer said so but still listed those passages as its sources. They are no longer returned; the trace keeps their count.

### Added: landing page, and the project is named AtaRehber
* **Landing page:** visitors first see what the assistant is (sources under every answer, no made-up answers, data stays on the organization's server) and how to use it in four steps, then go on to the login page with "Sohbete başla". Shown once per browser tab; the login page links back to it. Logged-in users go straight to the chat.
* **Lava lamp:** behind the landing page the colour fields rise and sink like wax in a lamp: a blob warms at the bottom, rises, cools at the top, and sinks again, clinging to others on the way (`web/src/lib/lava.ts`). It moves the same fields as the chat's background, so they roam on from where the lamp left them.
* **Name:** the repository, the docs, the API title, the Docker image tags, and the web UI's built-in name are now AtaRehber (before: OpenLocalRagAgents, OpenLocalEnterpriseRag, "OpenLocal Asistan"). Admins can still set another name under **Administration → Appearance**.

### Improved: ready to install for any organization
* **Texts per organization:** admins set the assistant's name, the welcome and disclaimer texts, up to six example questions, the example request, and the names of the profile fields, in Turkish and English, under **Administration → Appearance**. Empty fields keep the built-in texts, which no longer refer to a university ("Yıllık izin hakkı kaç gündür?" instead of the retirement age of faculty members). `UI_LANGUAGE` and `UI_DISCLAIMER` now apply to the React web UI.
* **Language model down:** while Ollama is stopped or lacks a model, questions get "The language model is not running right now" (HTTP 503, `X-Error-Code: llm_unavailable`) at once, instead of an answer that "could not be fully verified", which read like a problem with the documents (`LLM_STATUS_CHECK`).
* **Living background:** soft colour fields drift behind the web UI, cling together, pull apart, divide, and merge like cells, without outlines. While an answer is being prepared they gather at a random spot and merge; when it is in, they divide and scatter at the same pace to new random places, then calm down. Colours ease into each other instead of jumping.
* **The whole site changes colour while the assistant thinks:** each question turns the palette by a random angle (60-150 degrees); buttons, headings, badges, the logo, and the dark background turn with the background colours, and go back to the theme's colours while the answer's colours scatter. Green, amber, and red keep their meaning and do not change. Drawn on a small canvas scaled up by the browser (under 2 ms per frame, no GPU needed), still for users who prefer reduced motion.
* **Streamlit removed:** the HTTPS proxy serves the React web UI at `/`. `ui/`, `Dockerfile.frontend`, `requirements-ui.txt`, and the `frontend` compose service are gone; `CORS_ORIGINS` defaults to the web UI's address (port 8080).

### Improved: agents that work together
* **Composite questions:** a question that asks a rule and a database value at once ("En fazla kaç monitör alınabilir ve NovaView monitörün birim fiyatı nedir?") gets one step per agent; the combined answer may draw the conclusion (compare, subtract, say whether a condition is met). Measured: 4 of 4 composite questions planned with both agents (before: 1 of 4), all expected facts in the answers, routing on the main dataset 100%.
* **Steps that build on each other:** a plan step can use what an earlier step found (`"uses"`), e.g. the product with the lowest stock, then that product's return policy.
* **Questions back:** "Kaç gün izin hakkım var?" gets "Kıdeminiz kaç yıl?" with the options as buttons when the rules depend on seniority; the answer completes the original question. Only in a conversation, only for questions about the asker's own case (general questions get all the cases), never twice in a row (`CLARIFY_QUESTIONS`). Measured: asked on 3 of 3 ambiguous questions and on none of 8 clear ones.
* **Answers for the user's unit:** admins record each account's unit, program, and level; agents answer rules that differ by them for that user, and "bölümümde" is searched as the user's department.
* **Checked database answers:** every number must be a value of the query result; a wrong one is corrected once, then the rows are shown as a table.
* **Checked compliance verdicts:** the verdict and the rules it cites must be in the retrieved rules; otherwise it is revised once, then left `[UNDETERMINED]` with the advice to ask the responsible unit. Supported verdicts show their evidence.
* **Time limit per step:** a step slower than `AGENT_STEP_TIMEOUT_SECONDS` (180 s) is answered with "could not be completed in time"; the other steps still count.
* **Learning from unanswered questions:** "not found" answers now reach the review list (before, they were recorded as successful). Staff (admins and editors) answer them under **Administration → Review**; the answer is searchable at once, and everyone who asked sees it under the new bell in the header.
* **Requests from the chat:** "#12 numaralı talebimi iptal et" (after a yes) and "Talebime ekle: …"; without a number, the only open request is meant.
* **Agent performance:** **Administration → Performance** shows per agent the questions, median and slow answer times, unverified answers, errors, and thumbs up/down (the web UI now sends the rated agent).
* **Evaluation:** the `agents` stage (`evals/dataset_agents.jsonl`) measures plans, combined answers, and questions back.
* **Fixed:** policy section numbers and codes in answers ("Bölüm 2.1", "HR-POL-07") were taken for facts by the number check and could reject a correct answer; short Turkish request commands ("talebimi iptal et") were answered in English.

### Added: new web UI
* **React instead of Streamlit:** a new web UI in `web/` (React, TypeScript, Vite, Tailwind CSS) with a purple theme, light and dark mode, and Turkish and English texts. (Streamlit was removed in the next release.)
* **Chat:** answers appear as the stages progress ("Searching the documents…", "Checking the answer…") and can be stopped; each answer shows its verification level, the evidence with article and paragraph, the sources (used ones first), and the agents' steps. Conversations are listed on the side (a menu on phones) and kept in the browser; the agent can be chosen or left to the supervisor. A busy server gets its own message instead of an error. Cached data is cleared when the user changes, so the next person in the same browser tab never sees the previous user's requests or documents.
* **Service requests:** create, follow, and cancel requests; staff change the status and add a resolution note.
* **Administration:** documents (drag-and-drop upload, access groups), users, custom agents, answers to review, audit log with chain check, and system (statistics, database, backups, maintenance), each for the roles allowed to use it.
* **Guest access:** the login page offers the guest session when `GUEST_ACCESS_ENABLED=true`.
* **Nothing from the internet:** the font and all libraries are bundled; `npm run build` writes static files.
* **Deployment:** the `web` compose service (port 8080) serves the build with nginx and forwards `/api` to the backend, streaming answers as they come. The HTTPS proxy defines it as an upstream (see [Docker Deployment](docs/docker_deployment.md#-https-reverse-proxy)). CI checks types, runs the web tests, and builds the image.

### Improved: service requests from the chat
* **Requests about the conversation:** "open a request about this" takes its subject from the last turns; before, the agent saw only the message itself.
* **Users learn that they can:** greetings and thanks ("teşekkürler", "sağ olun", now answered without a model call) end with a hint on how to open a request, for logged-in users who can file them (not for guests). The web UI's request suggestion is a concrete example and is not shown to guests.
* **When the documents have no answer:** "not found" and unverified answers offer to pass the question on to the responsible unit ("bununla ilgili talep oluştur"), for the same users. The evaluation leaves the hint out when counting refusals.
* **Clearer drafts:** the title states the user's problem as the user put it, the category is shown by name ("Diğer", not `other`), and the draft says how to change it.

### Housekeeping
* **Unused code removed:** helpers nothing called anymore (`PasswordPolicy.is_valid`, the whole-PDF reader that page-aware reading replaced, `tool_description`, `doc_agent`'s own grade and refine wrappers that the shared answer check replaced), two test patches of those wrappers that had no effect, and unused texts in both web UIs.
* **Docs follow the new web UI:** where to create custom agents and sync database tables, the language of the UIs, browser token handling in the architecture, the rate limit for logins behind a proxy, and the web checks in [Contributing](CONTRIBUTING.md).

### Improved: token security for browsers
* **Refresh token in an HttpOnly cookie:** browser clients send `X-Token-Transport: cookie` and get the refresh token as a cookie that page scripts cannot read; the web UI keeps the access token in memory only. `POST /api/v1/auth/logout` deletes the cookie; `REFRESH_COOKIE_SECURE=true` sends it over HTTPS only (set by the HTTPS compose). Other clients get the refresh token in the body as before.

### Improved: answer check
* **Second opinion:** when the grader rejects an answer, it is shown its own objection and asked again before the answer is refined, as the 7B grader rejects correct answers now and then (`GRADER_SECOND_OPINION`).
* **Number check:** every number of an answer must be in the sentences the grader quoted, the question, or a tool result; "30 days" where the document says "15 days" fails even if the grader accepts it (`GRADER_NUMBER_CHECK`).
* **Transitional articles:** an answer that relies only on a transitional article while the provision in force was also found is sent back once (`GRADER_TRANSITIONAL_CHECK`).
* **Partial answers:** when the check keeps failing, the supported sentences are shown as "partly verified" instead of dropping the whole answer.
* **Three levels:** answers carry `verification` (`verified`, `partial`, `unverified`, with reasons); the web UI explains each, and a combined answer gets its weakest part's level. `src/agent/verification.py` is shared by `doc_agent` and custom agents.
* **Answers to review:** unverified answers are recorded with status `warning` and listed for admins together with answers rated down (`GET /api/v1/admin/review`, "Answers to Review").
* **Measuring the check:** `evals/build_grader_dataset.py` turns correct answers of a report into a dataset with wrong copies (a changed number, an invented sentence); the `grader` stage of `run_eval.py` reports how many correct answers are accepted and how many wrong ones rejected, for the grader alone and for the full check.

### Improved: answers from the documents
* **Evidence under the answer:** a verified answer shows the sentence it relies on, with article and paragraph ("📌 Evidence · Madde 30/2"). The sentences come from the grader's checked quotes, matched to the original text of the sources.
* **Clearer sources:** the sources the answer relies on come first, with the evidence in bold; other retrieved chunks of the same article are merged and listed as "other sections that may be relevant". Long chunks are shortened (full text on demand), the loader's header line is no longer repeated, and chunk numbers and scores are shown to admins and editors only.
* **"Could not be verified" points somewhere:** the unverified answer lists the sections that may still help.
* **Progress while waiting:** the web UI uses the streaming endpoint and shows the stages ("Searching the documents…", "Writing the answer…", "Checking the answer…") instead of a spinner.
* **Fixed: short follow-up questions were not rewritten.** Only questions with more than three words were turned into standalone search queries, so "Peki doktora için?" was searched as is. Now short questions and questions that refer back are rewritten.
* **Answer cache:** verified answers to first questions are reused for the same question, access, and documents (`ANSWER_CACHE_SIZE`, `ANSWER_CACHE_MINUTES`); uploads, deletions, and access changes invalidate them.
* **Evaluation:** the retrieval stage reports whether the expected facts are in the chosen chunks (the right document could be the wrong article) and compares candidate pools (`RAG_CANDIDATE_POOL`); the end-to-end stage reports facts in the returned sources and how many verified answers show evidence.
* **Experimental modes** (off by default, measured in [Evaluation](docs/evaluation.md)): `ANSWER_EVIDENCE_FIRST` (copy the evidence before answering) and `DOC_AGENT_TOOLS` (calculator and dates for `doc_agent`).

### Added: custom agents without code
* **Agents from the web UI:** admins create agents under **🧩 Custom Agents**: what the agent is for (the supervisor routes by it), its instructions, and its tools. The agent is available at once, without a restart, and appears in the agent choice. API: `GET`/`PUT`/`DELETE /api/v1/admin/custom-agents/{name}`, `GET /api/v1/admin/agent-tools`.
* **Tools:** document search (with the user's access groups), calculator (no code runs), date calculation, and read-only database queries. The model decides when to call them (Ollama tool calling).
* **Same safety rules:** fixed rules are added to every custom prompt, and answers based on documents pass the quote-based check of `doc_agent`, with computed values (a deadline, an average) as part of the context. The grade and refine steps moved to `src/agent/self_rag.py`, shared by both.
* **Language detection:** "Vize notum 50 … not ortalamam kaç olur?" was answered in English: "not" (a grade) is also an English word and "etkiliyorsa" was not recognized. The present tense "-yor" now counts inside words (etkiliyorsa, geliyorum), and Turkish letters decide a Turkish/English tie.

### Added: guest access and a busy answer
* **Guests (visitors without an account):** with `GUEST_ACCESS_ENABLED=true` the login panel offers "Continue as guest". Guests ask `doc_agent` about the documents shared with `GUEST_DOCUMENT_GROUP` (default `ziyaretci`) only, for example the open education faculty's regulations for prospective students; they cannot see internal documents, file requests, or query databases. Each guest session has its own question budget (`GUEST_RATE_LIMIT_PER_MINUTE`, default 10), lasts `GUEST_SESSION_MINUTES` (default 120), and cannot be refreshed; ending it clears the conversation for the next visitor on a shared computer. New endpoints `GET` / `POST /api/v1/auth/guest`. Documents shared with visitors are visible to every account as well.
* **Busy answer instead of a timeout:** at most `MAX_QUEUED_QUERIES` (default 10) questions wait for the model; further questions get HTTP 503 at once and the web UI says "the assistant is busy, try again in a minute".
* A pure greeting is answered as a greeting even when an agent is chosen.

### Fixed: web UI
* **Rate limit hit while uploading:** the web UI reloads its panels with several `GET` requests on every click (an admin's sidebar makes eight), which used up the 30 requests per minute, so an upload after a few clicks failed with HTTP 429. Reads now have their own budget, `RATE_LIMIT_READS_PER_MINUTE` (default 300); `RATE_LIMIT_PER_MINUTE` (30) still limits questions, uploads, and other changes.
* **Forced password change said "fill in all fields" although they were filled:** a text field only reports its value after Enter or leaving it, and a password the browser fills in may not reach the page. The three fields are now a form sent as a whole, carry `current-password` / `new-password` autocomplete hints, and the warning names the empty field.

### Improved: answer accuracy on laws and regulations
* **Article-aware chunking:** laws and regulations are split by article (`Madde 30 –`, `GEÇİCİ MADDE 2 –`, …). Every chunk names its document and article (`[YÜKSEKÖĞRETİM KANUNU | Madde 30 – Emeklilik yaş haddi]`), pieces of long articles repeat the sentence that introduces their list (which penalty the listed acts get), and footnotes and appendix tables are kept apart. Long articles are split at `ARTICLE_CHUNK_SIZE` (default 900 characters). Sources in answers show the article. Re-index existing documents to use it.
* **Numbers in words get their digits:** `elli beş puan` is indexed as `elli beş (55) puan`, so the model no longer prefers a superseded number written in digits in a transitional article.
* **Provisions in force first:** transitional articles and footnotes are placed last in the context.
* **Four chunks of context (`RERANKER_TOP_N=4`, was 3):** long articles are split into several pieces, and the fourth one often holds the rule; no change on the demo dataset, +0.2 s median latency.
* **Quote-based answer check:** the grader backs the facts of an answer with words copied from the documents, and the copies are verified in code (`GRADER_MODE=quotes`, default; `simple` restores the yes/no check). An objection the documents state word for word counts as a grader mistake when all numbers of the answer occur in the documents; a JSON reply Ollama aborts is retried without JSON mode.
* **Targeted refinement:** the grader's objection is passed to the refinement step, which corrects that claim instead of reducing a correct answer to "not in the documents".
* **Routing:** sub-questions the supervisor plans for the same agent are merged into one step with the user's question.
* **`OLLAMA_NUM_GPU`:** on a 6 GB card Ollama keeps a safety margin and runs about a fifth of qwen2.5:7b on the CPU. `OLLAMA_NUM_GPU=99` puts every layer on the GPU when it fits; measured on an RTX 3060 Laptop (6 GB): prompt processing 322 → 1273 tokens/s, generation 27 → 39 tokens/s.
* **Evaluation:** the university dataset has 127 questions over three documents (Law No. 2547, the Open Higher Education Regulation, and Atatürk University's undergraduate regulation). The harness caches the index per corpus and chunking settings (`evals/.cache/`), scores a pool of 50 candidates per question in the retrieval stage (`--retrieval-pool`), and can leave out the database agent like a deployment without a database (`--no-database`). An answer that contains every expected fact no longer counts as a refusal because of a phrase such as "fark bulunmamaktadır", and digits added to numbers in words ("on (10) iş günü") do not break fact matching.

### Changed: code cleanup and module layout
* **Removed unused code:** the single-agent Self-RAG graph the API no longer used (`src/agent/agent_graph.py`, `nodes.py`, `query_service.py`), the unused LangChain SQL tools (`src/agent/tools.py`, which opened its own database connection on import), the `src/config.py` bridge, `AgentResponse`, the `tools` attribute of sub-agents, and the vector-only backup function. The grading helpers moved to `src/agent/grading.py`.
* **No eager package imports:** `src/**/__init__.py` files only document their package. Before, `from src.core import config` loaded torch and created the user store; the test suite now starts in about half the time.
* **Clearer layout:** `src/core/` holds infrastructure only (settings, logging, audit trail); document access groups moved to `src/auth/document_access.py`; service requests, e-mail notifications, and backups (`src/services/backups.py`, out of `src/api/state.py`) live in `src/services/`. The database connector is split into `db_connector.py`, `sql_guard.py`, and `sample_db.py`.
* **Web UI split into modules:** `ui/app.py` (chat) plus `sidebar.py`, `components.py`, `api_client.py` (one request helper with token refresh instead of 15 copies of the same error handling), and `session.py`. Fixed: an answer whose grade merely contained "yes" (e.g. "no, not yes") was shown as verified.
* **Tests by topic:** `tests/agents/`, `rag/`, `api/`, `security/`, `data/`, `frontend/`, `quality/`, `performance/`. Tests of removed code were deleted; the resource profiling tests are opt-in (`RUN_PROFILE_TESTS=1`) and now measure the models rather than the library import.
* One launch target: `uvicorn src.main:app` (`src/api/main.py` no longer re-exports internal functions).

### Added: collaborating agents, service requests, document access groups
* **Several agents per question:** the supervisor returns a plan of up to `MAX_AGENT_STEPS` (default 3) steps, each an agent with its own sub-question. Composite questions run the agents one after another and a `synthesize` step combines their answers; the grading model checks the combined text against the parts and falls back to showing the parts when it adds anything. Results list the contributing agents (`agents`, `active_agent: "multi_agent"`); streaming sends `plan` events.
* **Handoffs:** an agent can map failure statuses to another agent (`handoff_on`) or request a handoff (`{"handoff": {"to": ...}}`). `db_agent` hands rejected queries, errors, and missing database connections to `doc_agent`, so "YÖK kaç üyeden oluşur?" no longer ends in an SQL error. Limited by `MAX_AGENT_HANDOFFS` (default 1); streaming sends `handoff` events.
* **Availability:** agents that cannot work right now (`is_available()`, e.g. `db_agent` without a database) are hidden from the supervisor, the heuristics, handoffs, and `GET /api/v1/agents`. `SAMPLE_DB_ENABLED=false` turns the demo database off for real deployments.
* **Service request agent (`request_agent`):** files requests from the chat after showing the draft and getting a "yes" (the draft is kept in the conversation; any other message discards it), and lists the user's requests. Requests live in `data/requests.db`. New endpoints `GET`/`POST /api/v1/requests` and `PATCH /api/v1/requests/{request_id}`: users see and cancel their own requests, staff (`admin`, `editor`) see all and change their status. Optional e-mail to the responsible unit through the organization's mail server (`SMTP_*`, `REQUEST_NOTIFY_EMAILS`, `REQUEST_NOTIFY_INCLUDE_DETAILS`); `REQUEST_RETENTION_DAYS` deletes closed requests. The assistant still has no internet access.
* **Document access groups:** users have `groups`; documents can be restricted to groups when uploading (`groups` form field) or later (`PUT /api/v1/documents/{filename}/access`). The vector search filters by the user's groups before reranking, and restricted documents are also hidden from viewers' document lists and statistics. Admins and editors see everything; existing documents stay public.
* **Per-task models:** `OLLAMA_ROUTER_MODEL` and `OLLAMA_GRADER_MODEL` (default: `OLLAMA_MODEL`); the startup check requires all of them to be pulled, and `GET /api/v1/stats` reports them.
* **Organization-neutral prompts:** "company" became "the organization" in prompts and fixed answers ("Bu bilgi kurum dokümanlarında bulunmuyor."), `ORGANIZATION_NAME` names the institution, and the compliance agent no longer recommends corporate roles such as the CISO. The document prompt now asks for the general rule before exceptions, prefers provisions in force over transitional articles and footnotes, and asks for article citations.
* **Database errors stay internal:** `db_agent` no longer shows the database error text to users; it stays in the trace.
* **Web UI:** "My Requests" panel (form, status, cancel; staff can change status), access groups when uploading and per document, user group management for admins, and trace entries for plans, handoffs, and combined answers.
* **Evaluation:** a university dataset (48 questions over the Higher Education Law No. 2547, `evals/dataset_university.jsonl`) and a `request` category; the harness now asks as a logged-in user and includes `request_agent`.

### Added: pilot readiness
* **HTTPS:** `docker-compose.https.yml` adds an nginx reverse proxy (TLS, HSTS, security headers, WebSocket and streaming support) and stops publishing the backend and UI ports. CI validates the nginx configuration and the compose overrides.
* **Retention (KVKK/GDPR):** `AUDIT_RETENTION_DAYS` and `SESSION_RETENTION_DAYS` delete old audit entries and conversations hourly. The audit hash chain stays verifiable after a purge (chain anchor), and each purge is logged. `AUDIT_STORE_QUESTIONS=false` keeps question text, answer previews, and feedback comments out of the audit log. New page: [Data Protection](docs/data_protection.md).
* **Full backups:** `POST /api/v1/admin/backup` now backs up the data directory (documents, users, audit log, conversations) together with the vector index, using the SQLite backup API for consistent copies. `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP` schedule them; `POST /api/v1/admin/maintenance/run` runs retention and backups on demand.
* **Web UI in Turkish and English:** Turkish by default (`UI_LANGUAGE`), switchable in the sidebar, with an AI disclaimer above the chat (`UI_DISCLAIMER` to customize). The agent trace now shows the SQL of `db_agent` queries (it looked for a field that does not exist).
* **Page numbers in citations:** PDF chunks record the page they start and end on; sources carry `page` / `page_end` and the UI shows them (e.g. "s. 4–5"). Re-upload existing PDFs to add page numbers.
* **No telemetry:** ChromaDB's anonymized telemetry (sent to an external analytics service by default) is disabled, and Streamlit usage statistics are disabled for local runs as well.

### Fixed: answers in the user's language
* Every agent now answers in the language of the question (Turkish or English). Before, only 63% of the Turkish evaluation questions got a Turkish answer: "not found" and fallback texts, the greeting, and database/compliance error messages were hard-coded in English, and `db_agent` summaries and compliance reports often switched to English, especially in follow-up questions. Now 100% match.
* New module `src/agent/language.py`: `response_language()` detects the language (a question without language cues, such as a ticket code, inherits the session's language), `language_instruction()` pins it in prompts, and `message()` returns the fixed texts in Turkish or English. The English constants `NO_CONTEXT_RESPONSE` / `FALLBACK_RESPONSE` remain for compatibility.
* Compliance reports use Turkish section headings for Turkish questions; verdict labels such as `[VIOLATION / PROHIBITED]` stay in English in both languages.
* The evaluation harness reports `language_match_rate` and recognizes the Turkish fixed answers as refusals.
* Questions in other languages are recognized as such (by script or function words) and answered in the question's language on a best-effort basis, with English fixed texts. A spot check answered Spanish and German questions correctly; Mandarin Chinese and Hindi are not usable yet.
* New [Language Support](docs/language_support.md) page: supported languages, behavior for other languages, how to add a language, and the languages coming next (Mandarin Chinese, Hindi, Spanish).

### ⚠️ Breaking: the LLM is served by Ollama only
* The in-process HuggingFace LLM backend was removed. The LLM always runs in an [Ollama](https://ollama.com) server (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, default `qwen2.5:7b`). Before upgrading, install Ollama and run `ollama pull qwen2.5:7b`.
* Removed settings: `LLM_BACKEND`, `LLM_MODEL_ID`, `LLM_MODEL_DIR` (a startup warning lists them if they are still set). New setting: `OLLAMA_NUM_CTX` (default 4096), because some Ollama versions default to a 2048-token context and silently cut long prompts.
* The API checks at startup that Ollama is reachable and the model is pulled, and logs the fix otherwise. `GET /api/v1/stats` reports it as `llm_status` and the UI shows a warning. The evaluation harness stops early with the same message.
* `download_model.py` downloads only the embedding and reranker models (~3.3 GB instead of ~6.4 GB). The old `models/qwen2.5-1.5b` folder is no longer used and can be deleted.
* Dependencies: `langchain-huggingface`, `accelerate`, and `bitsandbytes` were dropped. PyTorch only runs the retrieval models, so the CPU build is enough.
* **Measured effect:** on the evaluation set, `qwen2.5:7b` via Ollama answers 95% of questions correctly versus 73% for the removed in-process 1.5B model (routing 98% vs 82%, database questions 80% vs 40%). See the [Evaluation Guide](docs/evaluation.md#-current-results).
* Docker: the `ollama` service always runs (no `--profile ollama`), a one-shot `ollama-pull` service downloads the model on the first start, and `docker-compose.gpu.yml` gives the GPU to Ollama. Ollama's port is no longer published on the host, so it does not clash with an Ollama already running there.


### Added
* **Evaluation harness (`evals/`):** a labeled set of 51 questions over six policy documents and the sample database, and `python -m evals.run_eval`, which measures retrieval (hit rate, MRR, off-topic rejection, threshold sweeps), supervisor routing, and end-to-end answers (fact accuracy, refusals, Self-RAG grounding, latency). Reports can be compared run to run. See the [Evaluation Guide](docs/evaluation.md).
* **Database integration tests:** read-only enforcement is tested against real PostgreSQL and MySQL servers in CI.
* `RAGEngine` accepts `vector_db_path`, and `RAGEngine.search()` accepts `top_n` and `min_reranker_score`.
* **Relevance gate (`RAG_MIN_RERANKER_SCORE`, default `0.005`):** chunks the cross-encoder scores below the threshold are dropped. Off-topic questions now get no context, so `doc_agent` answers "not found" and `compliance_agent` returns `[UNDETERMINED]` instead of inventing an answer or a verdict (off-topic questions refused: 50% → 100% on the evaluation set).
* **Routing context for sub-agents:** `BaseSubAgent.get_routing_context()` lets an agent add live information to the supervisor prompt. `db_agent` lists the connected tables and columns (cached for 5 minutes), so database questions reach it (database routing: 0% → 70%).

### Changed
* **Python 3.12 or newer is required.** CI tests Python 3.12, 3.13, and 3.14, and the Docker images use `python:3.12-slim`. Python 3.10 and 3.11 are no longer supported.
* PyTorch installation instructions install only `torch`; the project never used `torchvision` or `torchaudio`.
* CI runs every Python version to completion and reports failing tests as GitHub annotations.
* **Routing:** narrower `doc_agent` and `compliance_agent` descriptions and ordered supervisor rules. Plain policy questions stay with `doc_agent`, and `compliance_agent` handles verdicts on a described action (overall routing accuracy: 67% → 82%).
* `compliance_agent` can return `[UNDETERMINED]` when the retrieved policies do not address the scenario, instead of choosing between compliant and violation.

### Security
* MySQL/MariaDB sessions are now read-only at session scope (`SET SESSION TRANSACTION READ ONLY`). The previous transaction-scoped mode could be ended by the implicit commit that DDL statements perform. The SQL guard already blocked DDL, so this hardens the second layer only.

---

## 🔧 Version 2.1.1 — Correctness & Security Hardening

### Fixed
* **Multi-turn memory in the multi-agent workflow:** turns are now appended to `chat_history` by a `record_turn` graph node and persisted per session by the checkpointer. Previously history was never written, so follow-up questions had no context.
* **Forced agent selection:** `forced_agent` is now part of `MultiAgentState`; LangGraph had been silently dropping it, so the UI agent selector had no effect on `/api/v1/query`.
* **Streaming uses the same graph as batch queries:** `/api/v1/query-stream` now shares memory and routing with `/api/v1/query`. A client disconnect stops the worker and keeps the concurrency gate until inference finishes.
* **Self-RAG restored:** `doc_agent` now grades answers, refines ungrounded drafts, and falls back safely. Grader failures count as unverified (fail closed). `hallucination_grade` / `is_refined` are populated again.
* **`db_agent`:** reports the real guard/database error message and row count; splits generated SQL with `sqlparse`, so semicolons inside string literals are handled.
* **Table re-sync** now removes previously indexed rows (the delete used a different source name than indexing).
* **Session cleanup** honors `max_age_days` and targets the multi-agent conversation store (it previously deleted every session in the legacy store).
* **Docker:** `/health` liveness endpoint; the old healthcheck hit an authenticated endpoint, so the frontend never started.
* **Docker configuration:** the backend now loads `.env` via `env_file`, and compose defaults use `${VAR:-default}`, so settings such as `LLM_BACKEND=ollama` in `.env` take effect. Previously `.env` only worked because it was copied into the image.
* **Docker backups & restore:** `./backups` is mounted (snapshots were lost when the container was recreated). The restore now swaps the vector DB's contents instead of renaming the directory, which failed on the bind mount.
* **Fresh installs:** the auto-generated sample database is connected on the first start instead of only after a restart.
* **Agents registered at runtime** are now routable: the orchestrator recompiles its workflow when the registry changes (they previously produced an empty answer). If the supervisor falls back and no `doc_agent` is registered, the user gets an explanatory message instead of an empty answer.
* **CI** now runs on `master`, uses a pinned ruff, and does not download model weights.

### Security
* Refresh tokens are no longer accepted as access tokens; password changes and account deactivation revoke existing tokens.
* The default `admin123` password must be changed at first login (`POST /api/v1/auth/change-password`); the password policy now also applies to password resets.
* Per-account login lockout after repeated failures; general rate limiting is per account instead of per IP.
* SQL guard rewritten with token-level analysis. It blocks multi-statements, `SELECT INTO`, `ATTACH`/`PRAGMA`, and file/network/sleep functions, and enforces the table allowlist across comma joins, quoted and schema-qualified names, and subqueries. Queries also run in database-enforced read-only sessions (SQLite `query_only`, PostgreSQL/MySQL read-only transactions with a statement timeout).
* Audit log entries form a SHA-256 hash chain; `GET /api/v1/admin/audit-verify` detects edited or deleted entries.
* Vector DB restore is staged and applied at startup instead of deleting the live database under a running server.
* The auto-generated JWT secret file (`data/.jwt_secret`) is created with owner-only permissions (`0600`) on POSIX systems.
* Internal exception details are no longer returned to API clients; questions are logged only at DEBUG level.

### Operations
* Separate lightweight `Dockerfile.frontend`; backend image defaults to CPU PyTorch (CUDA via the `docker-compose.gpu.yml` build arg) and runs as a non-root user.
* Requirements split into `requirements.txt` (backend), `requirements-ui.txt`, and `requirements-dev.txt`, with major-version upper bounds.
* New settings: `DATA_DIR`, `RERANKER_TOP_N`, `RAG_MIN_SIMILARITY`, `CHAT_HISTORY_MAX_TURNS`, `DB_QUERY_TIMEOUT_SECONDS`, `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_WINDOW_SECONDS`, `REQUIRE_DEFAULT_PASSWORD_CHANGE`.
* New vector collections use cosine distance; the similarity threshold is metric-independent, so existing L2 indexes keep working unchanged.

---

## 🌟 Version 2.1.0 — Pluggable Multi-Agent Ecosystem

AtaRehber has evolved from a single-agent RAG pipeline into an **extensible, modular, and pluggable Multi-Agent framework** powered by LangGraph. The platform now features an intelligent **Supervisor Orchestrator** paired with domain-specific **Specialist Sub-Agents**, complete with real-time execution trace auditing.

---

### 1. 🏗️ Modular Multi-Agent Framework (`src/agent/multi_agent/`)

A production-grade multi-agent architecture has been integrated into the core system:

* **[`BaseSubAgent`](src/agent/multi_agent/base.py)**:
  * Abstract base class defining the contract for all specialist sub-agents.
  * Standardized attributes (`name`, `display_name`, `description`, `version`) and execution lifecycle (`execute(state)`).
  * Direct access to shared local LLM backends (`chat_model`).

* **[`AgentRegistry`](src/agent/multi_agent/registry.py) & `@register_agent`**:
  * Central dynamic registry implementing the Registry Pattern.
  * Developers can register custom sub-agents with a single `@register_agent` class decorator.
  * Self-discovering metadata engine feeding the Supervisor router and REST API dynamically.

* **[`MultiAgentState`](src/agent/multi_agent/state.py)**:
  * Typed LangGraph state container handling question context, user identity, conversation thread ID, active routing target (`active_agent`), step-by-step audit trace (`agent_trace`), grounded citations, and hallucination verdicts.

* **[`SupervisorAgent`](src/agent/multi_agent/supervisor.py)**:
  * Central intent classifier and dynamic router.
  * Inspects registry metadata at runtime to route queries to the most suitable sub-agent or handles general conversational inquiries directly without triggering downstream retrieval.
  * Built-in guardrails, regex-based fast paths, and fallback mechanisms.

* **[`MultiAgentOrchestrator`](src/agent/multi_agent/orchestrator_graph.py)**:
  * Compiled LangGraph `StateGraph` managing node transitions, conditional routing edges, and execution loops.
  * Persistent SQLite checkpointer (`MemorySaver` / `multi_agent_conversations.db`) for user-isolated conversation memory.
  * Full support for synchronous queries (`query()`), real-time NDJSON event streaming (`stream_events()`), and explicit agent targeting (`forced_agent`).

---

### 2. 👥 Built-in Specialist Sub-Agents (`src/agent/multi_agent/sub_agents/`)

Three enterprise specialist sub-agents are packaged out of the box:

| Agent Identifier | Display Name | Domain Specialization |
| :--- | :--- | :--- |
| **`doc_agent`** | 📄 Document & Policy RAG Specialist | Dense vector retrieval (BGE-M3) with Cross-Encoder reranking over company documents (PDF, DOCX, TXT) with verified citations. |
| **`db_agent`** | 🗄️ SQL & Database Analyst | Schema inspection and AST-validated read-only SQL generation across relational databases (PostgreSQL, MySQL, SQLite, etc.) with automated result summarization. |
| **`compliance_agent`** | 🛡️ Enterprise Compliance Auditor | Formal corporate compliance evaluations checking queries against company policies and GDPR/KVKK rules, rendering structured verdicts (`COMPLIANT`, `WARNING`, `VIOLATION`). |

---

### 3. 🌐 REST API Gateway Upgrades (`src/api/`)

FastAPI services now natively support multi-agent routing and introspection:

* **New Endpoint — `GET /api/v1/agents`**:
  * Returns a dynamic catalog of all active sub-agents along with their capabilities, version, and display metadata.
* **Enhanced Endpoint — `POST /api/v1/query`**:
  * Accepts an optional `agent` parameter in [`QueryRequest`](src/api/schemas.py) (`auto` for Supervisor routing, or explicit sub-agent IDs).
  * Returns `active_agent` and a detailed `agent_trace` array capturing execution metrics, SQL queries, and search parameters.
* **Streaming Endpoint — `POST /api/v1/query-stream`**:
  * Emits streaming multi-agent event frames via NDJSON, including real-time active agent tags and audit milestones.
* **State Management (`src/api/state.py`)**:
  * Singleton provider `get_multi_agent_orchestrator()` with clean lifecycle resource disposal during shutdown.

---

### 4. 🎨 Enterprise Streamlit UI Enhancements (`ui/app.py`)

The enterprise web dashboard delivers transparent multi-agent visibility:

* **🤖 Specialist Agent Team Selector**:
  * Dynamic sidebar dropdown populated directly from `/api/v1/agents`, enabling users to select the automatic supervisor or force-delegate tasks to a specific specialist.
* **🏷️ Color-Coded Agent Badges**:
  * Distinct badges preceding assistant responses to denote the answering agent:
    * 👑 **Supervisor** (Direct Response)
    * 📄 **doc_agent** (Document RAG Specialist)
    * 🗄️ **db_agent** (SQL & Database Analyst)
    * 🛡️ **compliance_agent** (Enterprise Compliance Auditor)
* **🔍 Collapsible Execution Trace Panel**:
  * Interactive accordion below each response revealing internal execution steps, duration in milliseconds, generated SQL queries, and retrieval parameters.

---

### 5. 📚 Developer Guides & Reference Examples

* **[`docs/custom_agents_guide.md`](docs/custom_agents_guide.md)**:
  * Complete 3-step developer tutorial for creating custom sub-agents using `BaseSubAgent` and `@register_agent`.
* **[`examples/custom_agent_example.py`](examples/custom_agent_example.py)**:
  * Fully executable sample demonstrating a `CurrencyConverterAgent` with custom math processing and multi-agent integration.

---

### 6. 🧪 Comprehensive Test Suite

* **[`tests/test_multi_agent.py`](tests/agents/test_multi_agent.py)**:
  * Unit tests validating `BaseSubAgent`, `AgentRegistry`, `SupervisorAgent`, state handling, and LangGraph workflow orchestration.
* **[`tests/test_api_multi_agent.py`](tests/api/test_api_multi_agent.py)**:
  * Integration tests for `/api/v1/agents` authentication, response contracts, supervisor routing, and streaming output.

---

## 📋 File Modifications Summary

| Directory / File | Status | Description |
| :--- | :--- | :--- |
| `src/agent/multi_agent/base.py` | ✨ Added | Base abstract class (`BaseSubAgent`) for sub-agents |
| `src/agent/multi_agent/registry.py` | ✨ Added | Central agent registry and `@register_agent` decorator |
| `src/agent/multi_agent/state.py` | ✨ Added | Multi-Agent LangGraph state models |
| `src/agent/multi_agent/supervisor.py` | ✨ Added | Intelligent Supervisor intent classifier and router |
| `src/agent/multi_agent/orchestrator_graph.py` | ✨ Added | Compiled LangGraph multi-agent execution workflow |
| `src/agent/multi_agent/sub_agents/doc_agent.py` | ✨ Added | Document vector RAG specialist sub-agent |
| `src/agent/multi_agent/sub_agents/db_agent.py` | ✨ Added | SQL database analysis and safe query sub-agent |
| `src/agent/multi_agent/sub_agents/compliance_agent.py` | ✨ Added | Regulatory compliance and policy auditor sub-agent |
| `src/api/routes/query.py` | 📝 Modified | Added `/api/v1/agents` endpoint and multi-agent routing |
| `src/api/schemas.py` | 📝 Modified | Added `AgentInfo`, `AgentsListResponse`, and `agent` query field |
| `src/api/state.py` | 📝 Modified | Added `get_multi_agent_orchestrator()` and cleanup |
| `src/api/main.py` | 📝 Modified | Exported multi-agent orchestrator dependencies |
| `ui/app.py` | 📝 Modified | Added agent selector dropdown, badges, and trace panel |
| `docs/custom_agents_guide.md` | ✨ Added | Developer guide for building custom sub-agents |
| `examples/custom_agent_example.py` | ✨ Added | Working sample custom sub-agent implementation |
| `tests/test_multi_agent.py` | ✨ Added | Core multi-agent framework unit test suite |
| `tests/test_api_multi_agent.py` | ✨ Added | Multi-agent API integration test suite |
| `WHATSNEW.md` | ✨ Added | Comprehensive release notes and changelog |
