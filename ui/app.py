import os
import sys
import uuid

import requests
import streamlit as st

# The UI modules live next to this script (streamlit run ui/app.py)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import DEFAULT_UI_LANGUAGE, LANGUAGES, category_label, page_label, translate  # noqa: E402

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(
    page_title="OpenLocalRagAgents",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom styling
st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)


# ─────────────────────── SESSION STATE ───────────────────────
if "ui_language" not in st.session_state:
    st.session_state.ui_language = DEFAULT_UI_LANGUAGE
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "must_change_password" not in st.session_state:
    st.session_state.must_change_password = False
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:12]
if "selected_agent" not in st.session_state:
    st.session_state.selected_agent = "auto"
if "messages" not in st.session_state:
    # Fixed assistant texts are stored as keys, so they follow a later language switch
    st.session_state.messages = [
        {"role": "assistant", "text_key": "welcome", "sources": [], "active_agent": "supervisor"}
    ]


def t(key, **values):
    """Text in the language selected in the sidebar."""
    return translate(st.session_state.ui_language, key, **values)


# ─────────────────────── AUTHENTICATION HELPERS ───────────────────────
def is_password_change_pending():
    return bool(st.session_state.get("auth_token")) and st.session_state.get("must_change_password", False)


def store_tokens(data):
    """Persist a TokenResponse from login, refresh, or change-password in the session."""
    st.session_state.auth_token = data["access_token"]
    st.session_state.refresh_token = data.get("refresh_token", st.session_state.get("refresh_token"))
    st.session_state.user_info = {"username": data["username"], "role": data["role"]}
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
            return True, t("login_success")
        return False, res.json().get("detail", t("login_failed"))
    except Exception as e:
        return False, t("connection_error", error=e)


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
            return True, t("password_changed")
        return False, res.json().get("detail", t("password_change_failed"))
    except Exception as e:
        return False, t("connection_error", error=e)


def logout():
    st.session_state.auth_token = None
    st.session_state.refresh_token = None
    st.session_state.user_info = None
    st.session_state.must_change_password = False
    st.rerun()


# ─────────────────────── API HELPERS ───────────────────────
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


def upload_document(uploaded_file, groups=""):
    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        res = requests.post(
            f"{API_BASE_URL}/api/v1/upload-file",
            headers=get_auth_headers(),
            files=files,
            data={"groups": groups},
            timeout=600,
        )
        body = res.json()
        return res.status_code == 200, body.get("message") or body.get("detail") or t("unknown_response")
    except Exception as e:
        return False, str(e)


def api_error_detail(res):
    try:
        return res.json().get("detail") or res.text
    except Exception:
        return res.text


def set_document_access_api(filename, groups):
    try:
        res = requests.put(
            f"{API_BASE_URL}/api/v1/documents/{filename}/access",
            headers=get_auth_headers(),
            json={"groups": [g.strip() for g in groups.split(",") if g.strip()]},
            timeout=30,
        )
        return res.status_code == 200, t("access_saved") if res.status_code == 200 else api_error_detail(res)
    except Exception as e:
        return False, str(e)


def fetch_requests_api(all_users=False):
    try:
        res = requests.get(
            f"{API_BASE_URL}/api/v1/requests",
            headers=get_auth_headers(),
            params={"all_users": str(all_users).lower(), "limit": 30},
            timeout=5,
        )
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {"requests": [], "categories": []}


def create_request_api(category, title, description):
    try:
        res = requests.post(
            f"{API_BASE_URL}/api/v1/requests",
            headers=get_auth_headers(),
            json={"category": category, "title": title, "description": description},
            timeout=30,
        )
        if res.status_code == 201:
            return True, t("request_created_toast", id=res.json()["request"]["id"])
        return False, api_error_detail(res)
    except Exception as e:
        return False, str(e)


def update_request_api(request_id, status, note=""):
    try:
        res = requests.patch(
            f"{API_BASE_URL}/api/v1/requests/{request_id}",
            headers=get_auth_headers(),
            json={"status": status, "resolution_note": note},
            timeout=10,
        )
        return res.status_code == 200, t("request_updated") if res.status_code == 200 else api_error_detail(res)
    except Exception as e:
        return False, str(e)


def fetch_users_api():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/auth/users", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return []


def update_user_groups_api(username, groups):
    try:
        res = requests.patch(
            f"{API_BASE_URL}/api/v1/auth/users/{username}",
            headers=get_auth_headers(),
            json={"groups": [g.strip() for g in groups.split(",") if g.strip()]},
            timeout=10,
        )
        return res.status_code == 200, t("user_groups_saved") if res.status_code == 200 else api_error_detail(res)
    except Exception as e:
        return False, str(e)


def delete_document_api(filename):
    try:
        res = requests.delete(
            f"{API_BASE_URL}/api/v1/documents/{filename}",
            headers=get_auth_headers(),
            timeout=10,
        )
        return res.status_code == 200, res.json().get("message", t("deleted"))
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
        res = requests.get(f"{API_BASE_URL}/api/v1/admin/audit-stats", headers=get_auth_headers(), timeout=5)
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
        return res.status_code == 200, res.json().get("message", t("operation_completed"))
    except Exception as e:
        return False, str(e)


BUILT_IN_AGENTS = ("auto", "doc_agent", "db_agent", "compliance_agent", "request_agent")


def fetch_agents_api():
    try:
        res = requests.get(f"{API_BASE_URL}/api/v1/agents", headers=get_auth_headers(), timeout=5)
        if res.status_code == 200:
            return res.json().get("agents", [])
    except Exception:
        pass
    return [{"name": name, "display_name": name, "description": ""} for name in BUILT_IN_AGENTS]


def agent_label(agent):
    """Localized name for built-in agents; the API's display name for custom agents."""
    if agent["name"] in BUILT_IN_AGENTS:
        return t(f"agent_{agent['name']}")
    return agent.get("display_name") or agent["name"]


def agent_description(agent):
    if agent["name"] in BUILT_IN_AGENTS:
        return t(f"agent_desc_{agent['name']}")
    return agent.get("description", "")


def query_rag_api(question, agent=None):
    try:
        payload = {"question": question, "session_id": st.session_state.get("session_id")}
        if agent and agent not in ("auto", "none"):
            payload["agent"] = agent
        res = requests.post(f"{API_BASE_URL}/api/v1/query", headers=get_auth_headers(), json=payload, timeout=180)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            if refresh_token_api():
                return query_rag_api(question, agent=agent)
            return {"status": "error", "answer": t("session_expired"), "sources": []}
        return {"status": "error", "answer": t("api_error", error=res.text), "sources": []}
    except Exception as e:
        return {"status": "error", "answer": t("api_connection_error", error=e), "sources": []}


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


# ─────────────────────── RENDERING HELPERS ───────────────────────
AGENT_BADGE_STYLES = {
    "supervisor": "background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a;",
    "doc_agent": "background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;",
    "db_agent": "background-color: #f3e8ff; color: #6b21a8; border: 1px solid #e9d5ff;",
    "compliance_agent": "background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca;",
    "request_agent": "background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0;",
    "multi_agent": "background-color: #ede9fe; color: #5b21b6; border: 1px solid #ddd6fe;",
}
REQUEST_STATUSES = ("open", "in_progress", "resolved", "rejected", "cancelled")
DEFAULT_BADGE_STYLE = "background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;"


def render_agent_badge(agent_name, agents=None):
    if agent_name == "multi_agent":
        label = t("badge_multi_agent", agents=", ".join(agents or []))
    elif agent_name in AGENT_BADGE_STYLES:
        label = t(f"badge_{agent_name}")
    else:
        label = f"🤖 {agent_name}"
    style = AGENT_BADGE_STYLES.get(agent_name, DEFAULT_BADGE_STYLE)
    st.markdown(f'<span class="agent-badge" style="{style}">{label}</span>', unsafe_allow_html=True)


def render_trace(trace):
    with st.expander(t("trace_title", count=len(trace))):
        for index, step in enumerate(trace, 1):
            if step.get("action") == "handoff":
                st.markdown(
                    f"**{index}.** "
                    + t("trace_handoff", source=step.get("from_agent"), target=step.get("target_agent"))
                )
                continue
            if step.get("action") == "synthesize":
                st.markdown(f"**{index}.** " + t("trace_synthesize", agents=", ".join(step.get("combined_agents", []))))
                continue
            if step.get("plan"):
                st.caption(t("trace_plan", steps=" → ".join(f"`{p['agent']}`" for p in step["plan"])))
            st.markdown(
                f"**{index}. ⚙️ `{step.get('agent', 'agent')}`** — *{step.get('action', '')}* "
                f"(`{step.get('status', 'done')}`, `{step.get('duration_ms', 0)}ms`)"
            )
            if step.get("sql"):
                st.code(step["sql"], language="sql")
            if step.get("search_query"):
                st.caption(t("search_query", query=step["search_query"]))


def render_verification(is_refined, verified, has_sources):
    if is_refined:
        st.caption(t("audit_refined"))
    elif verified and has_sources:
        st.caption(t("audit_verified"))
    elif verified is False and has_sources:
        st.caption(t("audit_unverified"))


def render_sources(sources):
    with st.expander(t("sources_title", count=len(sources))):
        for index, source in enumerate(sources, 1):
            title = f"`{source.get('source', '?')}`"
            page = page_label(st.session_state.ui_language, source)
            if page:
                title += f" — {page}"
            details = [t("chunk", index=source.get("chunk_index", 0))]
            if source.get("reranker_score") is not None:
                details.append(t("score", score=source["reranker_score"]))
            st.markdown(f"**{index}. 📄 {title}** · {' · '.join(details)}")
            st.markdown(f'> *"{source.get("content", "").strip()}"*')


def render_assistant_extras(message):
    if message.get("agent_trace"):
        render_trace(message["agent_trace"])
    render_verification(message.get("is_refined"), message.get("verified"), bool(message.get("sources")))


# ─────────────────────── SIDEBAR ───────────────────────
with st.sidebar:
    st.selectbox(t("language_label"), options=list(LANGUAGES), format_func=LANGUAGES.get, key="ui_language")
    st.title(t("control_panel"))

    # ──── 1. Authentication ────
    if not st.session_state.auth_token:
        st.subheader(t("login_title"))
        login_user = st.text_input(t("username"), key="login_username", placeholder=t("username_placeholder"))
        login_pass = st.text_input(t("password"), type="password", key="login_password")
        if st.button(t("login_button"), use_container_width=True, type="primary"):
            if not login_user or not login_pass:
                st.warning(t("login_missing"))
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
        st.markdown(t("logged_in_as", user=user_info.get("username")))
        st.markdown(f'<span class="role-badge role-{role}">{role}</span>', unsafe_allow_html=True)
        if st.button(t("logout"), use_container_width=True):
            logout()
        st.divider()

    # ──── Mandatory password change (e.g. first login with the default admin password) ────
    if is_password_change_pending():
        st.subheader(t("change_password_title"))
        st.warning(t("change_password_required"))
        current_pw = st.text_input(t("current_password"), type="password", key="cp_current")
        new_pw = st.text_input(t("new_password"), type="password", key="cp_new")
        confirm_pw = st.text_input(t("confirm_password"), type="password", key="cp_confirm")
        if st.button(t("update_password"), use_container_width=True, type="primary"):
            if not current_pw or not new_pw:
                st.warning(t("password_fields_missing"))
            elif new_pw != confirm_pw:
                st.error(t("password_mismatch"))
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
            st.success(t("api_connected"))
            st.markdown(f"**LLM (Ollama):** `{stats.get('llm_model', '')}`")
            if stats.get("llm_status", "ok") != "ok":
                st.warning(stats["llm_status"])
            st.markdown(f"{t('retrieval_device')} `{stats.get('device', '?')}`")
            col1, col2 = st.columns(2)
            with col1:
                st.metric(t("total_documents"), stats.get("total_documents", 0))
            with col2:
                st.metric(t("vector_chunks"), stats.get("total_chunks", 0))
        else:
            st.error(t("api_offline"))
            st.info(t("start_backend_hint"))
        st.divider()

        # ──── Specialist agent selection ────
        st.subheader(t("agent_team"))
        agents_data = fetch_agents_api()
        agents_by_name = {a["name"]: a for a in agents_data}
        agent_names = list(agents_by_name)
        # Labels as options (not format_func) so the selection survives a language switch
        agent_labels = [agent_label(agents_by_name[name]) for name in agent_names]
        current_agent = st.session_state.get("selected_agent", "auto")
        chosen_label = st.selectbox(
            t("active_agent"),
            options=agent_labels,
            index=agent_names.index(current_agent) if current_agent in agent_names else 0,
            help=t("active_agent_help"),
        )
        selected_agent = agent_names[agent_labels.index(chosen_label)]
        st.session_state.selected_agent = selected_agent
        description = agent_description(agents_by_name[selected_agent])
        if description:
            st.caption(f"💡 *{description}*")
        st.divider()

        user_role = (st.session_state.user_info or {}).get("role", "viewer")

        # ──── 3. Document Upload (Admin & Editor only) ────
        if user_role in ["admin", "editor"]:
            st.subheader(t("upload_title"))
            uploaded_file = st.file_uploader(t("upload_label"), type=["pdf", "docx", "txt"], help=t("upload_help"))
            upload_groups = st.text_input(t("upload_groups"), key="upload_groups", help=t("upload_groups_help"))
            if uploaded_file is not None and st.button(t("upload_button"), use_container_width=True):
                with st.spinner(t("upload_spinner")):
                    success, msg = upload_document(uploaded_file, upload_groups)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(t("upload_failed", error=msg))
            st.divider()

        # ──── 4. Indexed Documents ────
        st.subheader(t("indexed_documents"))
        docs = fetch_documents()
        if docs:
            for doc in docs:
                col_info, col_del = st.columns([4, 1])
                with col_info:
                    meta = t("doc_meta", size=doc["size_kb"], chunks=doc["chunk_count"])
                    groups = doc.get("groups") or []
                    access = t("doc_groups", groups=", ".join(groups)) if groups else t("doc_public")
                    st.markdown(f"**{doc['filename']}**  \n<small>{meta} | {access}</small>", unsafe_allow_html=True)
                with col_del:
                    if user_role in ["admin", "editor"] and st.button(
                        "🗑️", key=f"del_{doc['filename']}", help=t("delete_help", name=doc["filename"])
                    ):
                        success, msg = delete_document_api(doc["filename"])
                        if success:
                            st.toast(t("deleted_toast", name=doc["filename"]), icon="🗑️")
                            st.rerun()
                        else:
                            st.error(msg)
                if user_role in ["admin", "editor"] and doc.get("chunk_count"):
                    with st.expander(t("doc_access_edit")):
                        new_groups = st.text_input(
                            t("upload_groups"),
                            value=", ".join(doc.get("groups") or []),
                            key=f"acl_{doc['filename']}",
                            help=t("upload_groups_help"),
                        )
                        if st.button(t("save"), key=f"acl_save_{doc['filename']}"):
                            ok, msg = set_document_access_api(doc["filename"], new_groups)
                            (st.success if ok else st.error)(msg)
                st.write("---")
        else:
            st.caption(t("no_documents"))
        st.divider()

        # ──── Service requests (everyone; staff can work off all requests) ────
        st.subheader(t("requests_title"))
        is_staff = user_role in ["admin", "editor"]
        show_all = is_staff and st.checkbox(t("requests_all"), key="requests_all")
        request_data = fetch_requests_api(all_users=show_all)
        categories = request_data.get("categories") or ["other"]
        with st.expander(t("request_new")):
            category_labels = [category_label(st.session_state.ui_language, c) for c in categories]
            chosen_category = st.selectbox(t("request_category"), category_labels, key="new_request_category")
            new_category = categories[category_labels.index(chosen_category)]
            new_title = st.text_input(t("request_title"), key="new_request_title")
            new_description = st.text_area(t("request_description"), key="new_request_description")
            if st.button(t("request_submit"), key="new_request_submit", use_container_width=True):
                ok, msg = create_request_api(new_category, new_title, new_description)
                if ok:
                    st.toast(msg, icon="📝")
                    st.rerun()
                else:
                    st.error(msg)
        requests_list = request_data.get("requests", [])
        if not requests_list:
            st.caption(t("requests_empty"))
        for req in requests_list:
            status_text = t(f"status_{req['status']}") if req["status"] in REQUEST_STATUSES else req["status"]
            category_text = category_label(st.session_state.ui_language, req["category"])
            with st.expander(f"#{req['id']} · {status_text} · {req['title'][:40]}"):
                st.caption(f"{category_text} · " + t("request_by", user=req["username"], date=req["created_at"][:16]))
                if req.get("description"):
                    st.markdown(req["description"])
                if req.get("resolution_note"):
                    st.info(req["resolution_note"])
                if is_staff:
                    status_labels = [t(f"status_{s}") for s in REQUEST_STATUSES]
                    chosen_status = st.selectbox(
                        t("request_status"),
                        status_labels,
                        index=REQUEST_STATUSES.index(req["status"]) if req["status"] in REQUEST_STATUSES else 0,
                        key=f"req_status_{req['id']}",
                    )
                    new_status = REQUEST_STATUSES[status_labels.index(chosen_status)]
                    note = st.text_input(
                        t("request_note"), value=req.get("resolution_note", ""), key=f"req_note_{req['id']}"
                    )
                    if st.button(t("request_update"), key=f"req_update_{req['id']}"):
                        ok, msg = update_request_api(req["id"], new_status, note)
                        (st.success if ok else st.error)(msg)
                elif req["status"] in ("open", "in_progress") and st.button(
                    t("request_cancel"), key=f"req_cancel_{req['id']}"
                ):
                    ok, msg = update_request_api(req["id"], "cancelled")
                    if ok:
                        st.rerun()
                    st.error(msg)
        st.divider()

        # ──── 5. Database Management (Admin only) ────
        if user_role == "admin":
            st.subheader(t("database"))
            db_data = fetch_database_status()
            if db_data and db_data.get("connection", {}).get("status") == "connected":
                conn = db_data["connection"]
                tables = conn.get("tables", [])
                st.success(t("db_connected", dialect=conn.get("dialect", "").upper()))
                st.caption(t("db_tables", count=len(tables)))
                if tables:
                    selected_table = st.selectbox(t("select_table"), tables)
                    if st.button(t("vectorize_button"), key="sync_table_btn", use_container_width=True):
                        with st.spinner(t("vectorize_spinner", table=selected_table)):
                            success, msg = sync_table_api(selected_table)
                            if success:
                                st.toast(msg, icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)
                    with st.expander(t("inspect_schema")):
                        st.code(db_data.get("schema_summary", t("schema_unavailable")), language="text")
            elif db_data and db_data.get("connection", {}).get("status") == "not_configured":
                st.caption(t("db_not_configured"))
                st.info(t("db_config_hint"))
            else:
                st.caption(t("db_offline"))
            st.divider()

            # ──── User groups for document access (Admin only) ────
            st.subheader(t("users_title"))
            with st.expander(t("users_title")):
                for user in fetch_users_api():
                    groups_value = st.text_input(
                        t("user_groups", user=user["username"], role=user["role"]),
                        value=", ".join(user.get("groups") or []),
                        key=f"user_groups_{user['username']}",
                        help=t("upload_groups_help"),
                    )
                    if st.button(t("save"), key=f"user_groups_save_{user['username']}"):
                        ok, msg = update_user_groups_api(user["username"], groups_value)
                        (st.success if ok else st.error)(msg)
            st.divider()

            # ──── 6. Audit Trail (Admin only) ────
            st.subheader(t("audit_trail"))
            with st.expander(t("audit_expander")):
                audit_stats = fetch_audit_stats()
                if audit_stats:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric(t("metric_total_events"), audit_stats.get("total_records", 0))
                        st.metric(t("metric_queries"), audit_stats.get("queries_executed", 0))
                        st.metric(t("metric_stream_queries"), audit_stats.get("stream_queries_executed", 0))
                    with c2:
                        st.metric(t("metric_uploads"), audit_stats.get("documents_uploaded", 0))
                        st.metric(t("metric_logins"), audit_stats.get("login_events", 0))
                        st.metric(t("metric_feedback"), audit_stats.get("feedback_events", 0))
                logs = fetch_audit_logs(limit=15)
                if logs:
                    st.write(t("latest_activity"))
                    for entry in logs:
                        badge = "🟢" if entry.get("status") == "success" else "🔴"
                        time_str = entry.get("timestamp", "").split("T")[-1][:8]
                        st.markdown(
                            f"{badge} `{time_str}` **{entry.get('username', '')}** "
                            f"[{entry.get('action', '').upper()}]: *{(entry.get('detail') or '')[:60]}*"
                        )
                else:
                    st.caption(t("no_audit_events"))
            st.divider()

        if st.button(t("clear_conversation"), use_container_width=True):
            st.session_state.session_id = uuid.uuid4().hex[:12]
            st.session_state.messages = [{"role": "assistant", "text_key": "conversation_cleared", "sources": []}]
            st.rerun()


# ─────────────────────── MAIN PANEL (CHAT) ───────────────────────
st.markdown(f'<div class="main-header">{t("main_title")}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-header">{t("subtitle")}</div>', unsafe_allow_html=True)

if not st.session_state.auth_token:
    st.info(t("auth_required"))
elif is_password_change_pending():
    st.warning(t("password_change_pending"))
else:
    st.info(t("disclaimer"))

    for msg_idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant" and msg.get("active_agent"):
                render_agent_badge(msg["active_agent"], msg.get("agents"))
            st.markdown(t(msg["text_key"]) if msg.get("text_key") else msg["content"])
            if msg["role"] == "assistant":
                render_assistant_extras(msg)

            # Feedback buttons for real answers (with sources)
            if msg["role"] == "assistant" and msg.get("sources") and msg_idx > 0:
                question = st.session_state.messages[msg_idx - 1].get("content", "")
                fb_col1, fb_col2, _ = st.columns([1, 1, 8])
                with fb_col1:
                    if st.button("👍", key=f"fb_up_{msg_idx}", help=t("feedback_up_help")):
                        submit_feedback_api(question, "positive")
                        st.toast(t("feedback_thanks"), icon="👍")
                with fb_col2:
                    if st.button("👎", key=f"fb_down_{msg_idx}", help=t("feedback_down_help")):
                        submit_feedback_api(question, "negative")
                        st.toast(t("feedback_recorded"), icon="📝")

            if msg.get("sources"):
                render_sources(msg["sources"])

    if prompt := st.chat_input(t("chat_placeholder")):
        st.session_state.messages.append({"role": "user", "content": prompt, "sources": []})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner(t("thinking")):
                res = query_rag_api(prompt, agent=st.session_state.get("selected_agent", "auto"))

            is_refined = res.get("is_refined", False)
            grade = str(res.get("hallucination_grade", "")).strip().lower()
            message = {
                "role": "assistant",
                "content": res.get("answer") or t("no_response"),
                "sources": res.get("sources", []),
                "verified": ("evet" in grade or "yes" in grade) or is_refined,
                "is_refined": is_refined,
                "active_agent": res.get("active_agent", "supervisor"),
                "agents": res.get("agents", []),
                "agent_trace": res.get("agent_trace", []),
            }
            render_agent_badge(message["active_agent"], message["agents"])
            st.markdown(message["content"])
            render_assistant_extras(message)
            if message["sources"]:
                render_sources(message["sources"])
            st.session_state.messages.append(message)
