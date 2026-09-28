"""Rendering helpers for chat messages: agent badges, execution trace, verification note, and sources."""

import html
import re

import streamlit as st

from i18n import page_label
from session import t, user_role

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
# Roles that see retrieval details (chunk numbers, reranker scores)
STAFF_ROLES = ("admin", "editor")
# Characters of a source shown before "show all"
SOURCE_PREVIEW_CHARS = 500
# Chunk header added by the document loader: "[YÜKSEKÖĞRETİM KANUNU | Madde 30 – Emeklilik yaş haddi]"
_CHUNK_HEADER = re.compile(r"^\[[^\]\n]*\]\n")

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
    .evidence {
        border-left: 4px solid #0ea5e9; background-color: rgba(14, 165, 233, 0.08);
        padding: 8px 12px; border-radius: 4px; margin: 6px 0;
    }
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
    if message.get("is_refined") and message.get("verified"):
        st.caption(t("audit_refined"))
    elif message.get("verified"):
        st.caption(t("audit_verified"))
    elif message.get("verified") is False:
        st.caption(t("audit_unverified"))
        # No verified answer: point to the sections that may still help
        sections = list(dict.fromkeys(section_label(source) for source in message["sources"]))[:3]
        st.info(t("related_sections", sections=", ".join(sections)))


def document_name(source: dict) -> str:
    """File name without extension, e.g. 'ATATÜRK ÜNİVERSİTESİ ÖN LİSANS VE LİSANS YÖNETMELİĞİ'."""
    return re.sub(r"\.(txt|pdf|docx)$", "", str(source.get("source", "?")), flags=re.IGNORECASE)


def section_label(source: dict) -> str:
    """'Madde 30' for legislation chunks, the page for PDFs, otherwise the document name."""
    article = str(source.get("article") or "").split(" – ")[0]
    return article or page_label(st.session_state.ui_language, source) or document_name(source)


def source_text(source: dict) -> str:
    """Chunk text without the loader's header line (the title shows document and article already)."""
    return _CHUNK_HEADER.sub("", str(source.get("content", "")), count=1).strip()


def render_evidence(sources: list) -> None:
    """The sentences the answer relies on, with their citation: '📌 Dayanak (Madde 30/2)'."""
    evidence = [(item, source) for source in sources for item in source.get("evidence", [])]
    if not evidence:
        return
    for item, source in evidence:
        citation = html.escape(item.get("citation") or section_label(source))
        document, sentence = html.escape(document_name(source)), html.escape(item["text"])
        st.markdown(
            f'<div class="evidence">📌 <b>{t("evidence_title")}</b> · {citation} · <i>{document}</i>'
            f"<br>“{sentence}”</div>",
            unsafe_allow_html=True,
        )


def _source_preview(text: str, highlight: list) -> str:
    """Up to SOURCE_PREVIEW_CHARS around the first highlighted sentence, with the sentences in bold."""
    start = min((text.find(h) for h in highlight if h in text), default=0)
    begin = max(0, start - SOURCE_PREVIEW_CHARS // 3) if start > SOURCE_PREVIEW_CHARS // 2 else 0
    preview = text[begin : begin + SOURCE_PREVIEW_CHARS]
    for sentence in highlight:
        if sentence in preview:
            preview = preview.replace(sentence, f"**{sentence}**")
    return ("…" if begin else "") + preview + ("…" if begin + SOURCE_PREVIEW_CHARS < len(text) else "")


def _render_source(source: dict, index: int, staff: bool) -> None:
    title = document_name(source)
    page = page_label(st.session_state.ui_language, source)
    for part in (page, source.get("article")):
        if part:
            title += f" — {part}"
    details = ""
    if staff:
        parts = [t("chunk", index=source.get("chunk_index", 0))]
        if source.get("reranker_score") is not None:
            parts.append(t("score", score=source["reranker_score"]))
        details = " · " + " · ".join(parts)
    st.markdown(f"**{index}. 📄 {title}**{details}")
    text = source_text(source)
    highlight = [item["text"] for item in source.get("evidence", [])]
    st.markdown("> " + _source_preview(text, highlight).replace("\n", "\n> "))
    if len(text) > SOURCE_PREVIEW_CHARS:
        with st.popover(t("source_full_text")):
            st.markdown(text)


def render_sources(sources: list) -> None:
    """Sources the answer relies on first; other retrieved sections of the same article are merged."""
    staff = user_role() in STAFF_ROLES
    groups, order = {}, []
    for source in sources:
        key = (source.get("source"), source.get("article") or source.get("chunk_index"))
        if key not in groups:
            groups[key] = source
            order.append(key)
        elif source.get("used") and not groups[key].get("used"):
            groups[key] = source
    unique = [groups[key] for key in order]
    used = [source for source in unique if source.get("used")]
    others = [source for source in unique if not source.get("used")]
    with st.expander(t("sources_title", count=len(unique))):
        for index, source in enumerate(used + others, 1):
            if used and others and index == len(used) + 1:
                st.caption(t("sources_related"))
            _render_source(source, index, staff)


def render_assistant_message(message: dict, text: str) -> None:
    """Badge, answer, trace, verification note, and sources of one assistant message."""
    if message.get("active_agent"):
        render_agent_badge(message["active_agent"], message.get("agents"))
    st.markdown(text)
    if message.get("verified"):
        render_evidence(message.get("sources", []))
    if message.get("agent_trace"):
        render_trace(message["agent_trace"])
    render_verification(message)
