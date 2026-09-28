"""Sidebar: login, system status, agent choice, documents, service requests, and administration."""

import streamlit as st

import api_client as api
from components import BUILT_IN_AGENTS, REQUEST_STATUSES, agent_description, agent_label
from i18n import LANGUAGES, category_label
from session import (
    is_guest,
    is_logged_in,
    is_password_change_pending,
    logout,
    new_conversation,
    start_conversation,
    t,
    user_role,
)

STAFF_ROLES = ("admin", "editor")


def render_sidebar() -> None:
    with st.sidebar:
        st.selectbox(t("language_label"), options=list(LANGUAGES), format_func=LANGUAGES.get, key="ui_language")
        st.title(t("control_panel"))
        _account()
        if is_password_change_pending():
            _password_change()
        if not is_logged_in() or is_password_change_pending():
            return
        if is_guest():
            # Guests only chat: no system details, agent choice, documents, or requests
            if st.button(t("clear_conversation"), use_container_width=True):
                new_conversation()
                st.rerun()
            return
        _system_status()
        _agent_choice()
        role = user_role()
        if role in STAFF_ROLES:
            _document_upload()
        _documents(can_manage=role in STAFF_ROLES)
        _service_requests(is_staff=role in STAFF_ROLES)
        if role == "admin":
            _database()
            _custom_agents()
            _user_groups()
            _audit_trail()
        if st.button(t("clear_conversation"), use_container_width=True):
            new_conversation()
            st.rerun()


def _show(ok: bool, message: str) -> None:
    (st.success if ok else st.error)(message)


def _account() -> None:
    if not is_logged_in():
        st.subheader(t("login_title"))
        username = st.text_input(t("username"), key="login_username", placeholder=t("username_placeholder"))
        password = st.text_input(t("password"), type="password", key="login_password")
        if st.button(t("login_button"), use_container_width=True, type="primary"):
            if not username or not password:
                st.warning(t("login_missing"))
            else:
                ok, message = api.login(username, password)
                _show(ok, message)
                if ok:
                    st.rerun()
        if api.guest_access_enabled():
            st.caption(t("guest_help"))
            if st.button(t("guest_button"), use_container_width=True):
                ok, message = api.start_guest_session()
                if ok:
                    start_conversation("welcome_guest")
                    st.rerun()
                st.error(message)
    elif is_guest():
        st.markdown(f"**{t('guest_badge')}**")
        if st.button(t("guest_end"), use_container_width=True):
            # Shared computers (library, kiosk): the next visitor must not see this conversation
            start_conversation("welcome")
            logout()
    else:
        user_info = st.session_state.user_info or {}
        role = user_info.get("role", "viewer")
        st.markdown(t("logged_in_as", user=user_info.get("username")))
        st.markdown(f'<span class="role-badge role-{role}">{role}</span>', unsafe_allow_html=True)
        if st.button(t("logout"), use_container_width=True):
            logout()
    st.divider()


def _password_change() -> None:
    """Mandatory after the first login with the default admin password."""
    st.subheader(t("change_password_title"))
    st.warning(t("change_password_required"))
    # A form sends all three fields when the button is pressed; single inputs only report their value after Enter
    # or leaving the field. The autocomplete hints stop password managers from putting the old password into
    # the new-password fields.
    with st.form("password_change_form"):
        current = st.text_input(
            t("current_password"), type="password", key="cp_current", autocomplete="current-password"
        )
        new = st.text_input(t("new_password"), type="password", key="cp_new", autocomplete="new-password")
        confirm = st.text_input(t("confirm_password"), type="password", key="cp_confirm", autocomplete="new-password")
        submitted = st.form_submit_button(t("update_password"), use_container_width=True, type="primary")
    if submitted:
        empty = [label for label, value in ((t("current_password"), current), (t("new_password"), new)) if not value]
        if empty:
            # A browser may show a saved password it has not handed to the page yet; naming the field helps
            st.warning(t("password_fields_missing", fields=", ".join(empty)))
        elif new != confirm:
            st.error(t("password_mismatch"))
        else:
            ok, message = api.change_password(current, new)
            _show(ok, message)
            if ok:
                st.rerun()
    st.divider()


def _system_status() -> None:
    stats = api.get_stats()
    if stats:
        st.success(t("api_connected"))
        st.markdown(f"**LLM (Ollama):** `{stats.get('llm_model', '')}`")
        if stats.get("llm_status", "ok") != "ok":
            st.warning(stats["llm_status"])
        st.markdown(f"{t('retrieval_device')} `{stats.get('device', '?')}`")
        col1, col2 = st.columns(2)
        col1.metric(t("total_documents"), stats.get("total_documents", 0))
        col2.metric(t("vector_chunks"), stats.get("total_chunks", 0))
    else:
        st.error(t("api_offline"))
        st.info(t("start_backend_hint"))
    st.divider()


def _agent_choice() -> None:
    st.subheader(t("agent_team"))
    agents = {agent["name"]: agent for agent in api.get_agents(BUILT_IN_AGENTS)}
    names = list(agents)
    # Labels as options (not format_func) so the selection survives a language switch
    labels = [agent_label(agents[name]) for name in names]
    current = st.session_state.get("selected_agent", "auto")
    chosen = st.selectbox(
        t("active_agent"),
        options=labels,
        index=names.index(current) if current in names else 0,
        help=t("active_agent_help"),
    )
    st.session_state.selected_agent = names[labels.index(chosen)]
    description = agent_description(agents[st.session_state.selected_agent])
    if description:
        st.caption(f"💡 *{description}*")
    st.divider()


def _document_upload() -> None:
    st.subheader(t("upload_title"))
    uploaded_file = st.file_uploader(t("upload_label"), type=["pdf", "docx", "txt"], help=t("upload_help"))
    groups = st.text_input(t("upload_groups"), key="upload_groups", help=t("upload_groups_help"))
    if uploaded_file is not None and st.button(t("upload_button"), use_container_width=True):
        with st.spinner(t("upload_spinner")):
            ok, message = api.upload_document(uploaded_file, groups)
        if ok:
            st.success(message)
            st.rerun()
        st.error(t("upload_failed", error=message))
    st.divider()


def _documents(can_manage: bool) -> None:
    st.subheader(t("indexed_documents"))
    documents = api.get_documents()
    if not documents:
        st.caption(t("no_documents"))
    for doc in documents:
        name = doc["filename"]
        col_info, col_delete = st.columns([4, 1])
        groups = doc.get("groups") or []
        access = t("doc_groups", groups=", ".join(groups)) if groups else t("doc_public")
        meta = t("doc_meta", size=doc["size_kb"], chunks=doc["chunk_count"])
        col_info.markdown(f"**{name}**  \n<small>{meta} | {access}</small>", unsafe_allow_html=True)
        if can_manage and col_delete.button("🗑️", key=f"del_{name}", help=t("delete_help", name=name)):
            ok, message = api.delete_document(name)
            if ok:
                st.toast(t("deleted_toast", name=name), icon="🗑️")
                st.rerun()
            st.error(message)
        if can_manage and doc.get("chunk_count"):
            with st.expander(t("doc_access_edit")):
                new_groups = st.text_input(
                    t("upload_groups"), value=", ".join(groups), key=f"acl_{name}", help=t("upload_groups_help")
                )
                if st.button(t("save"), key=f"acl_save_{name}"):
                    _show(*api.set_document_access(name, new_groups))
        st.write("---")
    st.divider()


def _service_requests(is_staff: bool) -> None:
    """Everyone files and follows their own requests; staff can work off all requests."""
    st.subheader(t("requests_title"))
    show_all = is_staff and st.checkbox(t("requests_all"), key="requests_all")
    data = api.get_requests(all_users=show_all)
    language = st.session_state.ui_language

    with st.expander(t("request_new")):
        categories = data.get("categories") or ["other"]
        category_labels = [category_label(language, c) for c in categories]
        chosen = st.selectbox(t("request_category"), category_labels, key="new_request_category")
        title = st.text_input(t("request_title"), key="new_request_title")
        description = st.text_area(t("request_description"), key="new_request_description")
        if st.button(t("request_submit"), key="new_request_submit", use_container_width=True):
            ok, message = api.create_request(categories[category_labels.index(chosen)], title, description)
            if ok:
                st.toast(message, icon="📝")
                st.rerun()
            st.error(message)

    requests_list = data.get("requests", [])
    if not requests_list:
        st.caption(t("requests_empty"))
    status_labels = [t(f"status_{s}") for s in REQUEST_STATUSES]
    for req in requests_list:
        status = req["status"]
        status_text = t(f"status_{status}") if status in REQUEST_STATUSES else status
        with st.expander(f"#{req['id']} · {status_text} · {req['title'][:40]}"):
            by = t("request_by", user=req["username"], date=req["created_at"][:16])
            st.caption(f"{category_label(language, req['category'])} · {by}")
            if req.get("description"):
                st.markdown(req["description"])
            if req.get("resolution_note"):
                st.info(req["resolution_note"])
            if is_staff:
                chosen_status = st.selectbox(
                    t("request_status"),
                    status_labels,
                    index=REQUEST_STATUSES.index(status) if status in REQUEST_STATUSES else 0,
                    key=f"req_status_{req['id']}",
                )
                note = st.text_input(
                    t("request_note"), value=req.get("resolution_note", ""), key=f"req_note_{req['id']}"
                )
                if st.button(t("request_update"), key=f"req_update_{req['id']}"):
                    _show(*api.update_request(req["id"], REQUEST_STATUSES[status_labels.index(chosen_status)], note))
            elif status in ("open", "in_progress") and st.button(t("request_cancel"), key=f"req_cancel_{req['id']}"):
                ok, message = api.update_request(req["id"], "cancelled")
                if ok:
                    st.rerun()
                st.error(message)
    st.divider()


def _database() -> None:
    st.subheader(t("database"))
    data = api.get_database_status() or {}
    connection = data.get("connection", {})
    if connection.get("status") == "connected":
        tables = connection.get("tables", [])
        st.success(t("db_connected", dialect=connection.get("dialect", "").upper()))
        st.caption(t("db_tables", count=len(tables)))
        if tables:
            table = st.selectbox(t("select_table"), tables)
            if st.button(t("vectorize_button"), key="sync_table_btn", use_container_width=True):
                with st.spinner(t("vectorize_spinner", table=table)):
                    ok, message = api.sync_table(table)
                if ok:
                    st.toast(message, icon="✅")
                    st.rerun()
                st.error(message)
            with st.expander(t("inspect_schema")):
                st.code(data.get("schema_summary", t("schema_unavailable")), language="text")
    elif connection.get("status") == "not_configured":
        st.caption(t("db_not_configured"))
        st.info(t("db_config_hint"))
    else:
        st.caption(t("db_offline"))
    st.divider()


def _agent_form(agent: dict, tools: list, key: str, is_new: bool) -> None:
    """Form to create or edit a custom agent; tools are chosen by their labels."""
    labels = {tool["name"]: tool["label"] for tool in tools}
    with st.form(f"custom_agent_{key}"):
        if is_new:
            name = st.text_input(t("custom_agent_name"), help=t("custom_agent_name_help"))
        else:
            name = agent["name"]
            st.caption(t("custom_agent_system_name", name=name))
        display_name = st.text_input(t("custom_agent_display_name"), value=agent.get("display_name", ""))
        description = st.text_area(
            t("custom_agent_description"), value=agent.get("description", ""), help=t("custom_agent_description_help")
        )
        instructions = st.text_area(
            t("custom_agent_instructions"),
            value=agent.get("instructions", ""),
            height=150,
            help=t("custom_agent_instructions_help"),
        )
        chosen = st.multiselect(
            t("custom_agent_tools"),
            options=list(labels.values()),
            default=[labels[name] for name in agent.get("tools", []) if name in labels],
            help="\n\n".join(f"{tool['label']}: {tool['description']}" for tool in tools),
        )
        enabled = st.checkbox(t("custom_agent_enabled"), value=agent.get("enabled", True))
        submitted = st.form_submit_button(t("custom_agent_create") if is_new else t("save"), type="primary")
    if submitted:
        by_label = {label: name for name, label in labels.items()}
        definition = {
            "name": name.strip(),
            "display_name": display_name.strip(),
            "description": description.strip(),
            "instructions": instructions.strip(),
            "tools": [by_label[label] for label in chosen],
            "enabled": enabled,
        }
        ok, message = api.save_custom_agent(definition)
        _show(ok, message)
        if ok:
            st.rerun()


def _custom_agents() -> None:
    """Agents defined here: what they are for, instructions, and tools; the supervisor routes to them."""
    st.subheader(t("custom_agents_title"))
    tools = api.get_agent_tools()
    with st.expander(t("custom_agents_title")):
        st.caption(t("custom_agents_help"))
        for agent in api.get_custom_agents():
            state = t("custom_agent_active") if agent.get("available") else t("custom_agent_inactive")
            st.markdown(f"**{agent['display_name']}** (`{agent['name']}`) · {state}")
            with st.popover(t("custom_agent_edit")):
                _agent_form(agent, tools, key=agent["name"], is_new=False)
                if st.button(t("custom_agent_delete"), key=f"custom_agent_delete_{agent['name']}"):
                    ok, message = api.delete_custom_agent(agent["name"])
                    _show(ok, message)
                    if ok:
                        st.rerun()
        st.markdown(f"**{t('custom_agent_new')}**")
        _agent_form({}, tools, key="new", is_new=True)
    st.divider()


def _user_groups() -> None:
    """Document access groups of every account."""
    st.subheader(t("users_title"))
    with st.expander(t("users_title")):
        for user in api.get_users():
            groups = st.text_input(
                t("user_groups", user=user["username"], role=user["role"]),
                value=", ".join(user.get("groups") or []),
                key=f"user_groups_{user['username']}",
                help=t("upload_groups_help"),
            )
            if st.button(t("save"), key=f"user_groups_save_{user['username']}"):
                _show(*api.set_user_groups(user["username"], groups))
    st.divider()


def _audit_trail() -> None:
    st.subheader(t("audit_trail"))
    with st.expander(t("audit_expander")):
        stats = api.get_audit_stats()
        if stats:
            col1, col2 = st.columns(2)
            col1.metric(t("metric_total_events"), stats.get("total_records", 0))
            col1.metric(t("metric_queries"), stats.get("queries_executed", 0))
            col1.metric(t("metric_stream_queries"), stats.get("stream_queries_executed", 0))
            col2.metric(t("metric_uploads"), stats.get("documents_uploaded", 0))
            col2.metric(t("metric_logins"), stats.get("login_events", 0))
            col2.metric(t("metric_feedback"), stats.get("feedback_events", 0))
        logs = api.get_audit_logs(limit=15)
        if not logs:
            st.caption(t("no_audit_events"))
        else:
            st.write(t("latest_activity"))
        for entry in logs:
            badge = "🟢" if entry.get("status") == "success" else "🔴"
            time_str = entry.get("timestamp", "").split("T")[-1][:8]
            st.markdown(
                f"{badge} `{time_str}` **{entry.get('username', '')}** "
                f"[{entry.get('action', '').upper()}]: *{(entry.get('detail') or '')[:60]}*"
            )
    st.divider()
