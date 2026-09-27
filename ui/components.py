"""Rendering helpers for chat messages: agent badges, execution trace, verification note, and sources."""

import re

import streamlit as st

from i18n import page_label
from session import t

BUILT_IN_AGENTS = ("auto", "doc_agent", "db_agent", "compliance_agent", "request_agent")
REQUEST_STATUSES = ("open", "in_progress", "resolved", "rejected", "cancelled")
AGENT_BADGE_STYLES = {
    "supervisor": "background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a;",
    "doc_agent": "background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;",
    "db_agent": "background-color: #f3e8ff; color: #6b21a8; border: 1px solid #e9d5ff;",
    "compliance_agent": "background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca;",
    "request_agent": "background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0;",
    "multi_agent": "background-color: #ede9fe; color: #5b21b6; border: 1px solid #ddd6fe;",
}
DEFAULT_BADGE_STYLE = "background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;"

PAGE_STYLE = """
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.05rem; color: #6c757d; margin-bottom: 1.5rem; }
    .role-badge {
        display: inline-block; padding: 4px 10px; border-radius: 12px;
        font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    }
    .role-admin { background-color: #dc3545; color: white; }
    .role-editor { background-color: #0d6efd; color: white; }
    .role-viewer { background-color: #198754; color: white; }
    .agent-badge {
        display: inline-block; padding: 3px 10px; border-radius: 12px;
        font-size: 0.8rem; font-weight: 600; margin-bottom: 6px;
    }
</style>
"""


def grade_passed(grade) -> bool:
    """Same rule as the backend: only a verdict whose first word is yes/evet counts as verified."""
    words = re.findall(r"\w+", str(grade or "").lower())
    return bool(words) and words[0] in ("yes", "evet")


def agent_label(agent: dict) -> str:
    """Localized name for built-in agents; the API's display name for custom agents."""
    if agent["name"] in BUILT_IN_AGENTS:
        return t(f"agent_{agent['name']}")
    return agent.get("display_name") or agent["name"]


def agent_description(agent: dict) -> str:
    if agent["name"] in BUILT_IN_AGENTS:
        return t(f"agent_desc_{agent['name']}")
    return agent.get("description", "")


def render_agent_badge(agent_name: str, agents=None) -> None:
    if agent_name == "multi_agent":
        label = t("badge_multi_agent", agents=", ".join(agents or []))
    elif agent_name in AGENT_BADGE_STYLES:
        label = t(f"badge_{agent_name}")
    else:
        label = f"🤖 {agent_name}"
    style = AGENT_BADGE_STYLES.get(agent_name, DEFAULT_BADGE_STYLE)
    st.markdown(f'<span class="agent-badge" style="{style}">{label}</span>', unsafe_allow_html=True)


def render_trace(trace: list) -> None:
    with st.expander(t("trace_title", count=len(trace))):
        for index, step in enumerate(trace, 1):
            if step.get("action") == "handoff":
                handoff = t("trace_handoff", source=step.get("from_agent"), target=step.get("target_agent"))
                st.markdown(f"**{index}.** {handoff}")
                continue
            if step.get("action") == "synthesize":
                combined = t("trace_synthesize", agents=", ".join(step.get("combined_agents", [])))
                st.markdown(f"**{index}.** {combined}")
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


def render_verification(message: dict) -> None:
    if not message.get("sources"):
        return
    if message.get("is_refined"):
        st.caption(t("audit_refined"))
    elif message.get("verified"):
        st.caption(t("audit_verified"))
    elif message.get("verified") is False:
        st.caption(t("audit_unverified"))


def render_sources(sources: list) -> None:
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


def render_assistant_message(message: dict, text: str) -> None:
    """Badge, answer, trace, verification note, and sources of one assistant message."""
    if message.get("active_agent"):
        render_agent_badge(message["active_agent"], message.get("agents"))
    st.markdown(text)
    if message.get("agent_trace"):
        render_trace(message["agent_trace"])
    render_verification(message)
