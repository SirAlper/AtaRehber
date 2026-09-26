import os
import uuid
import streamlit as st
import requests
import json

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(
    page_title="OpenLocalRagAgents",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #6c757d;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px;
        border-left: 4px solid #009688;
        margin-bottom: 10px;
    }
    .source-box {
        background-color: rgba(0, 150, 136, 0.08);
        border-radius: 6px;
        padding: 10px;
        margin-top: 8px;
        border-left: 3px solid #009688;
        font-size: 0.9rem;
    }
    .role-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .role-admin { background-color: #dc3545; color: white; }
    .role-editor { background-color: #0d6efd; color: white; }
    .role-viewer { background-color: #198754; color: white; }
    .agent-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────── AUTHENTICATION STATE & HELPERS ───────────────────────
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "must_change_password" not in st.session_state:
    st.session_state.must_change_password = False


def is_password_change_pending():
    return bool(st.session_state.get("auth_token")) and st.session_state.get("must_change_password", False)


def store_tokens(data):
    """Persist a TokenResponse from login, refresh, or change-password in the session."""
    st.session_state.auth_token = data["access_token"]
    st.session_state.refresh_token = data.get("refresh_token", st.session_state.get("refresh_token"))
    st.session_state.user_info = {
        "username": data["username"],
        "role": data["role"]
    }
    st.session_state.must_change_password = data.get("must_change_password", False)


def get_auth_headers():
    token = st.session_state.get("auth_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def login_api(username, password):
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        if res.status_code == 200:
            store_tokens(res.json())
            return True, "Login successful!"
        else:
            detail = res.json().get("detail", "Invalid username or password.")
            return False, detail
    except Exception as e:
        return False, f"Connection error: {e}"


def refresh_token_api():
    """Attempt to refresh the access token using the stored refresh token."""
    refresh = st.session_state.get("refresh_token")
    if not refresh:
        return False
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/auth/refresh",
            json={"refresh_token": refresh},
            timeout=10,
        )
        if res.status_code == 200:
            store_tokens(res.json())
            return True
    except Exception:
        pass
    return False


def change_password_api(current_password, new_password):
    """Change the logged-in user's password; the API returns fresh tokens (old ones are revoked)."""
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/auth/change-password",
            headers=get_auth_headers(),
            json={"current_password": current_password, "new_password": new_password},
            timeout=10,
        )
        if res.status_code == 200:
            store_tokens(res.json())
            return True, "Password changed successfully."
        return False, res.json().get("detail", "Password change failed.")
    except Exception as e:
        return False, f"Connection error: {e}"


def logout():
    st.session_state.auth_token = None
    st.session_state.refresh_token = None
    st.session_state.user_info = None
    st.session_state.must_change_password = False
    st.rerun()


# ─────────────────────── API HELPER FUNCTIONS ───────────────────────
def fetch_stats():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/stats", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            if refresh_token_api():
                return fetch_stats()
    except Exception:
        return None
    return None


def fetch_documents():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/documents", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("documents", [])
    except Exception:
        return []
    return []


def upload_document(uploaded_file):
    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        res = requests.post(
            f"{API_BASE_URL}/api/v1/upload-file",
            headers=get_auth_headers(),
            files=files,
            timeout=60,
        )
        return res.status_code == 200, res.json().get("message", "Unknown response.")
    except Exception as e:
        return False, str(e)


def delete_document_api(filename):
    try:
        res = requests.delete(
            f"{API_BASE_URL}/api/v1/documents/{filename}",
            headers=get_auth_headers(),
            timeout=10,
        )
        return res.status_code == 200, res.json().get("message", "Deleted.")
    except Exception as e:
        return False, str(e)


def fetch_database_status():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/database/status", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        return None
    return None


def fetch_audit_logs(limit=20):
    try:
        res = requests.get(
            f"{API_BASE_URL}/api/v1/admin/audit-logs?limit={limit}",
            headers=get_auth_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            return res.json().get("logs", [])
    except Exception:
        return []
    return []


def fetch_audit_stats():
    try:
        res = requests.get(
            f"{API_BASE_URL}/api/v1/admin/audit-stats",
            headers=get_auth_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            return res.json()
    except Exception:
        return None
    return None


def sync_table_api(table_name):
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/database/sync-table",
            headers=get_auth_headers(),
            json={"table_name": table_name},
            timeout=60,
        )
        return res.status_code == 200, res.json().get("message", "Operation completed.")
    except Exception as e:
        return False, str(e)


def fetch_agents_api():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/agents", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("agents", [])
    except Exception:
        pass
    return [
        {
            "name": "auto",
            "display_name": "👑 Otomatik (Supervisor Orchestrator)",
            "description": "Soruyu otomatik analiz edip en uygun uzman ajana veya doğrudan genel yanıta yönlendirir.",
            "version": "2.0.0",
        },
        {
            "name": "doc_agent",
            "display_name": "📄 Belge & Politika RAG Ajanı",
            "description": "Şirket içi dokümanlardan semantik arama ve doğrulanmış yanıt üretimi.",
            "version": "1.0.0",
        },
        {
            "name": "db_agent",
            "display_name": "🗄️ SQL Veritabanı Uzmanı",
            "description": "SQL sorguları ve salt-okunur veritabanı analitiği.",
            "version": "1.0.0",
        },
        {
            "name": "compliance_agent",
            "display_name": "🛡️ Mevzuat & Uyum Denetçisi",
            "description": "Kurumsal politika, KVKK ve mevzuat uygunluk denetimi.",
            "version": "1.0.0",
        },
    ]


def query_rag_api(question, agent=None):
    try:
        session_id = st.session_state.get("session_id")
        payload = {"question": question, "session_id": session_id}
        if agent and agent not in ("auto", "none"):
            payload["agent"] = agent
        res = requests.post(
            f"{API_BASE_URL}/api/v1/query",
            headers=get_auth_headers(),
            json=payload,
            timeout=180,
        )
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            if refresh_token_api():
                return query_rag_api(question, agent=agent)
            return {"status": "error", "answer": "Session expired. Please log in again.", "sources": []}
        return {"status": "error", "answer": f"Error: {res.text}", "sources": []}
    except Exception as e:
        return {"status": "error", "answer": f"API Connection Error: {e}", "sources": []}


def submit_feedback_api(question, feedback, comment=""):
    """Submit answer feedback (thumbs up/down) to the API."""
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/feedback",
            headers=get_auth_headers(),
            json={"question": question, "feedback": feedback, "comment": comment},
            timeout=10,
        )
        return res.status_code == 200
    except Exception:
        return False


# ─────────────────────── SESSION STATE INITIALIZATION ───────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:12]

if "selected_agent" not in st.session_state:
    st.session_state.selected_agent = "auto"

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Hello! I am your enterprise local AI assistant. I can answer questions grounded strictly in your internal documents, SQL databases, and corporate compliance regulations.",
            "sources": [],
            "active_agent": "supervisor",
        }
    ]


# ─────────────────────── SIDEBAR (CONTROL & AUTH PANEL) ───────────────────────
with st.sidebar:
    st.title("⚙️ Control Panel")

    # ──── 1. Authentication Section ────
    if not st.session_state.auth_token:
        st.subheader("🔐 Enterprise Login")
        login_user = st.text_input("Username", key="login_username", placeholder="e.g., admin")
        login_pass = st.text_input("Password", type="password", key="login_password")
        if st.button("Log In", use_container_width=True, type="primary"):
            if not login_user or not login_pass:
                st.warning("Please enter username and password.")
            else:
                success, msg = login_api(login_user, login_pass)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        st.divider()
    else:
        user_info = st.session_state.user_info or {}
        role = user_info.get("role", "viewer")
        st.markdown(f"👤 Logged in as: **{user_info.get('username')}**")
        badge_class = f"role-{role}"
        st.markdown(f'<span class="role-badge {badge_class}">{role}</span>', unsafe_allow_html=True)
        if st.button("Log Out", use_container_width=True):
            logout()
        st.divider()

    # ──── Mandatory password change (e.g. first login with the default admin password) ────
    if is_password_change_pending():
        st.subheader("🔑 Change Password")
        st.warning("You must set a new password before using the assistant.")
        current_pw = st.text_input("Current password", type="password", key="cp_current")
        new_pw = st.text_input("New password", type="password", key="cp_new")
        confirm_pw = st.text_input("Confirm new password", type="password", key="cp_confirm")
        if st.button("Update Password", use_container_width=True, type="primary"):
            if not current_pw or not new_pw:
                st.warning("Please fill in all password fields.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            else:
                ok, msg = change_password_api(current_pw, new_pw)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        st.divider()

    # ──── 2. System Status ────
    if st.session_state.auth_token and not is_password_change_pending():
        stats = fetch_stats()
        if stats:
            st.success("🟢 API Connected")
            st.markdown(f"**Device:** `{stats.get('device', 'Unknown')}`")
            st.markdown(f"**Model:** `{stats.get('llm_model', '').split('/')[-1]}`")

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Documents", stats.get("total_documents", 0))
            with col2:
                st.metric("Vector Chunks", stats.get("total_chunks", 0))
        else:
            st.error("🔴 API Offline or Session Expired")
            st.info("Start backend: `uvicorn src.api.main:app --reload`")

        st.divider()

        # ──── Multi-Agent Team Selection ────
        st.subheader("🤖 Specialist Agent Team")
        agents_data = fetch_agents_api()
        agent_names = [a["name"] for a in agents_data]
        agent_display_map = {a["name"]: a["display_name"] for a in agents_data}
        agent_desc_map = {a["name"]: a.get("description", "") for a in agents_data}

        current_agent = st.session_state.get("selected_agent", "auto")
        current_index = agent_names.index(current_agent) if current_agent in agent_names else 0

        selected_agent = st.selectbox(
            "Active Specialist Agent:",
            options=agent_names,
            index=current_index,
            format_func=lambda k: agent_display_map.get(k, k),
            help="Select the specialist agent to handle your query. In 'Auto' mode, the Supervisor Agent automatically classifies intent and delegates to the most appropriate specialist or responds directly.",
        )
        st.session_state.selected_agent = selected_agent
        if selected_agent in agent_desc_map:
            st.caption(f"💡 *{agent_desc_map[selected_agent]}*")

        st.divider()

        user_role = (st.session_state.user_info or {}).get("role", "viewer")

        # ──── 3. Document Upload (Admin & Editor only) ────
        if user_role in ["admin", "editor"]:
            st.subheader("📤 Upload Document")
            uploaded_file = st.file_uploader(
                "Choose a PDF, Word, or TXT file",
                type=["pdf", "docx", "txt"],
                help="Uploaded files are automatically parsed, contextualized, and indexed into ChromaDB."
            )
            if uploaded_file is not None:
                if st.button("🚀 Upload and Index", use_container_width=True):
                    with st.spinner("Parsing and vectorizing document..."):
                        success, msg = upload_document(uploaded_file)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(f"Upload failed: {msg}")

            st.divider()

        # ──── 4. Indexed Documents List & Deletion ────
        st.subheader("📚 Indexed Documents")
        docs = fetch_documents()
        if docs:
            for doc in docs:
                col_info, col_del = st.columns([4, 1])
                with col_info:
                    st.markdown(f"**{doc['filename']}**  \n<small>{doc['size_kb']} KB | {doc['chunk_count']} chunks</small>", unsafe_allow_html=True)
                with col_del:
                    if user_role in ["admin", "editor"]:
                        if st.button("🗑️", key=f"del_{doc['filename']}", help=f"Delete '{doc['filename']}'"):
                            success, msg = delete_document_api(doc['filename'])
                            if success:
                                st.toast(f"'{doc['filename']}' deleted!", icon="🗑️")
                                st.rerun()
                            else:
                                st.error(msg)
                st.write("---")
        else:
            st.caption("No indexed documents found.")

        st.divider()

        # ──── 5. Database Management (Admin only) ────
        if user_role == "admin":
            st.subheader("🗄️ Database")
            db_data = fetch_database_status()
            if db_data and db_data.get("connection", {}).get("status") == "connected":
                conn = db_data["connection"]
                dialect = conn.get("dialect", "").upper()
                tables = conn.get("tables", [])
                st.success(f"🟢 **{dialect}** Connected")
                st.caption(f"Accessible Tables: {len(tables)}")

                if tables:
                    selected_table = st.selectbox("Select Table to Vectorize", tables)
                    if st.button("🔄 Vectorize Table", key="sync_table_btn", use_container_width=True):
                        with st.spinner(f"Vectorizing table '{selected_table}'..."):
                            success, msg = sync_table_api(selected_table)
                            if success:
                                st.toast(msg, icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)

                    with st.expander("🔍 Inspect Database Schema"):
                        st.code(db_data.get("schema_summary", "Schema unavailable."), language="text")
            elif db_data and db_data.get("connection", {}).get("status") == "not_configured":
                st.caption("⚪ Database Not Configured")
                st.info("Optional: Set DATABASE_URL in .env to connect PostgreSQL, MSSQL, MySQL, Oracle, or SQLite.")
            else:
                st.caption("⚪ Database Offline")

            st.divider()

            # ──── 6. Audit & Compliance Log Inspector (Admin only) ────
            st.subheader("🛡️ Audit Trail")
            with st.expander("📋 View Compliance Logs & Metrics"):
                audit_stats = fetch_audit_stats()
                if audit_stats:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric("Total Events", audit_stats.get("total_records", 0))
                        st.metric("Queries", audit_stats.get("queries_executed", 0))
                        st.metric("Stream Queries", audit_stats.get("stream_queries_executed", 0))
                    with c2:
                        st.metric("Uploads", audit_stats.get("documents_uploaded", 0))
                        st.metric("Logins", audit_stats.get("login_events", 0))
                        st.metric("Feedback", audit_stats.get("feedback_events", 0))

                logs = fetch_audit_logs(limit=15)
                if logs:
                    st.write("**Latest Activity:**")
                    for l in logs:
                        badge = "🟢" if l.get("status") == "success" else "🔴"
                        time_str = l.get("timestamp", "").split("T")[-1][:8]
                        action_str = l.get("action", "").upper()
                        user_str = l.get("username", "")
                        detail_str = l.get("detail", "")
                        st.markdown(f"{badge} `{time_str}` **{user_str}** [{action_str}]: *{detail_str[:60]}*")
                else:
                    st.caption("No audit events recorded yet.")

            st.divider()

        if st.button("🧹 Clear Conversation", use_container_width=True):
            st.session_state.session_id = uuid.uuid4().hex[:12]
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": "Conversation history cleared. Ready for new questions!",
                    "sources": []
                }
            ]
            st.rerun()


# ─────────────────────── MAIN PANEL (CHAT) ───────────────────────
st.markdown('<div class="main-header">🏢 OpenLocalRagAgents Assistant</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Zero-leakage, on-premise generative AI assistant running 100% locally on your infrastructure.</div>', unsafe_allow_html=True)

if not st.session_state.auth_token:
    st.info("🔒 **Authentication Required:** Please log in using the Control Panel in the sidebar to access the Enterprise Assistant.")
elif is_password_change_pending():
    st.warning("🔑 **Password Change Required:** Set a new password in the sidebar to continue.")
else:
    # Render Message History
    for msg_idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg.get("role") == "assistant" and msg.get("active_agent"):
                agent_name = msg["active_agent"]
                if agent_name == "supervisor":
                    badge_label = "👑 Supervisor (Direct Response)"
                    badge_style = "background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a;"
                elif agent_name == "doc_agent":
                    badge_label = "📄 doc_agent (Document RAG Specialist)"
                    badge_style = "background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;"
                elif agent_name == "db_agent":
                    badge_label = "🗄️ db_agent (SQL Database Analyst)"
                    badge_style = "background-color: #f3e8ff; color: #6b21a8; border: 1px solid #e9d5ff;"
                elif agent_name == "compliance_agent":
                    badge_label = "🛡️ compliance_agent (Compliance Auditor)"
                    badge_style = "background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca;"
                else:
                    badge_label = f"🤖 {agent_name}"
                    badge_style = "background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;"

                st.markdown(
                    f'<span class="agent-badge" style="{badge_style}">{badge_label}</span>',
                    unsafe_allow_html=True,
                )

            st.markdown(msg["content"])

            # Render Agent Trace if present
            if msg.get("agent_trace"):
                with st.expander(f"🔍 Agent Execution Trace ({len(msg['agent_trace'])} Steps)"):
                    for t_idx, step in enumerate(msg["agent_trace"], 1):
                        step_agent = step.get("agent", "agent")
                        step_action = step.get("action", "")
                        step_duration = step.get("duration_ms", 0)
                        step_status = step.get("status", "done")
                        st.markdown(f"**{t_idx}. ⚙️ `{step_agent}`** — *{step_action}* (`{step_status}`, `{step_duration}ms`)")
                        if "query" in step:
                            st.code(step["query"], language="sql")
                        if "search_query" in step:
                            st.caption(f"Search Query: `{step['search_query']}`")

            # Audit & Verification Badges
            if msg.get("is_refined") is True:
                st.caption("✍️ *LangGraph Audit: Response re-evaluated and refined according to company documents.*")
            elif msg.get("verified") is True and msg.get("sources"):
                st.caption("🛡️ *LangGraph Audit: Verified directly against company documents.*")
            elif msg.get("verified") is False and msg.get("sources"):
                st.caption("⚠️ *LangGraph Audit: Could not be fully verified against company documents.*")

            # Feedback Buttons (for assistant messages with actual answers)
            if msg.get("role") == "assistant" and msg.get("sources") and msg_idx > 0:
                fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 8])
                with fb_col1:
                    if st.button("👍", key=f"fb_up_{msg_idx}", help="This answer was helpful"):
                        q = st.session_state.messages[msg_idx - 1].get("content", "") if msg_idx > 0 else ""
                        submit_feedback_api(q, "positive")
                        st.toast("Thank you for your feedback!", icon="👍")
                with fb_col2:
                    if st.button("👎", key=f"fb_down_{msg_idx}", help="This answer was not helpful"):
                        q = st.session_state.messages[msg_idx - 1].get("content", "") if msg_idx > 0 else ""
                        submit_feedback_api(q, "negative")
                        st.toast("Feedback recorded. We'll work to improve!", icon="📝")

            # Render Referenced Sources
            if msg.get("sources"):
                with st.expander(f"📚 Referenced Sources ({len(msg['sources'])} Chunks)"):
                    for idx, src in enumerate(msg["sources"], 1):
                        distance_info = f" (Distance: {src['distance']})" if src.get("distance") is not None else ""
                        reranker_info = f" | Score: {src['reranker_score']}" if src.get("reranker_score") is not None else ""
                        st.markdown(f"**{idx}. 📄 `{src['source']}` — Chunk #{src['chunk_index']}{distance_info}{reranker_info}**")
                        st.markdown(f"> *\"{src['content'].strip()}\"*")
                        st.write("")

    # User Input
    if prompt := st.chat_input("Ask a question about your enterprise documents, database, or compliance..."):
        # Append user message
        st.session_state.messages.append({"role": "user", "content": prompt, "sources": []})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Query Backend with Thinking Spinner
        with st.chat_message("assistant"):
            selected_agent = st.session_state.get("selected_agent", "auto")
            with st.spinner("💭 Multi-Agent team is analyzing and preparing response..."):
                res = query_rag_api(prompt, agent=selected_agent)

            answer = res.get("answer", "No response received.")
            sources = res.get("sources", [])
            active_agent = res.get("active_agent", "supervisor")
            agent_trace = res.get("agent_trace", [])
            is_refined = res.get("is_refined", False)
            grade = str(res.get("hallucination_grade", "")).strip().lower()
            is_verified = ("evet" in grade or "yes" in grade) or is_refined

            if active_agent == "supervisor":
                badge_label = "👑 Supervisor (Direct Response)"
                badge_style = "background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a;"
            elif active_agent == "doc_agent":
                badge_label = "📄 doc_agent (Document RAG Specialist)"
                badge_style = "background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;"
            elif active_agent == "db_agent":
                badge_label = "🗄️ db_agent (SQL Database Analyst)"
                badge_style = "background-color: #f3e8ff; color: #6b21a8; border: 1px solid #e9d5ff;"
            elif active_agent == "compliance_agent":
                badge_label = "🛡️ compliance_agent (Compliance Auditor)"
                badge_style = "background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca;"
            else:
                badge_label = f"🤖 {active_agent}"
                badge_style = "background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;"

            st.markdown(
                f'<span class="agent-badge" style="{badge_style}">{badge_label}</span>',
                unsafe_allow_html=True,
            )

            # Render complete answer
            st.markdown(answer)

            # Render trace
            if agent_trace:
                with st.expander(f"🔍 Agent Execution Trace ({len(agent_trace)} Steps)"):
                    for t_idx, step in enumerate(agent_trace, 1):
                        step_agent = step.get("agent", "agent")
                        step_action = step.get("action", "")
                        step_duration = step.get("duration_ms", 0)
                        step_status = step.get("status", "done")
                        st.markdown(f"**{t_idx}. ⚙️ `{step_agent}`** — *{step_action}* (`{step_status}`, `{step_duration}ms`)")
                        if "query" in step:
                            st.code(step["query"], language="sql")
                        if "search_query" in step:
                            st.caption(f"Search Query: `{step['search_query']}`")

            # Audit Badges
            if is_refined:
                st.caption("✍️ *LangGraph Audit: Response re-evaluated and refined according to company documents.*")
            elif is_verified and sources:
                st.caption("🛡️ *LangGraph Audit: Verified directly against company documents.*")
            elif not is_verified and sources:
                st.caption("⚠️ *LangGraph Audit: Could not be fully verified against company documents.*")

            # Referenced Sources
            if sources:
                with st.expander(f"📚 Referenced Sources ({len(sources)} Chunks)"):
                    for idx, src in enumerate(sources, 1):
                        distance_info = f" (Distance: {src['distance']})" if src.get("distance") is not None else ""
                        reranker_info = f" | Score: {src['reranker_score']}" if src.get("reranker_score") is not None else ""
                        st.markdown(f"**{idx}. 📄 `{src['source']}` — Chunk #{src['chunk_index']}{distance_info}{reranker_info}**")
                        st.markdown(f"> *\"{src['content'].strip()}\"*")
                        st.write("")

            # Save to session history
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "sources": sources,
                "verified": is_verified,
                "is_refined": is_refined,
                "active_agent": active_agent,
                "agent_trace": agent_trace,
            })

