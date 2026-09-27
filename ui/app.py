"""Streamlit web UI: `streamlit run ui/app.py`. Page layout and chat; see sidebar.py for the control panel."""

import os
import sys

import streamlit as st

# The UI modules live next to this script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_client as api  # noqa: E402
from components import PAGE_STYLE, grade_passed, render_assistant_message, render_sources  # noqa: E402
from session import init_session_state, is_logged_in, is_password_change_pending, t  # noqa: E402
from sidebar import render_sidebar  # noqa: E402

st.set_page_config(page_title="OpenLocalRagAgents", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")
st.markdown(PAGE_STYLE, unsafe_allow_html=True)
init_session_state()
render_sidebar()


def render_feedback_buttons(index: int) -> None:
    question = st.session_state.messages[index - 1].get("content", "")
    col_up, col_down, _ = st.columns([1, 1, 8])
    if col_up.button("👍", key=f"fb_up_{index}", help=t("feedback_up_help")):
        api.send_feedback(question, "positive")
        st.toast(t("feedback_thanks"), icon="👍")
    if col_down.button("👎", key=f"fb_down_{index}", help=t("feedback_down_help")):
        api.send_feedback(question, "negative")
        st.toast(t("feedback_recorded"), icon="📝")


def answer(prompt: str) -> dict:
    """Ask the API and turn the response into a stored chat message."""
    with st.spinner(t("thinking")):
        response = api.ask(prompt, agent=st.session_state.get("selected_agent", "auto"))
    return {
        "role": "assistant",
        "content": response.get("answer") or t("no_response"),
        "sources": response.get("sources", []),
        "verified": grade_passed(response.get("hallucination_grade")),
        "is_refined": response.get("is_refined", False),
        "active_agent": response.get("active_agent", "supervisor"),
        "agents": response.get("agents", []),
        "agent_trace": response.get("agent_trace", []),
    }


st.markdown(f'<div class="main-header">{t("main_title")}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-header">{t("subtitle")}</div>', unsafe_allow_html=True)

if not is_logged_in():
    st.info(t("auth_required"))
elif is_password_change_pending():
    st.warning(t("password_change_pending"))
else:
    st.info(t("disclaimer"))

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            text = t(message["text_key"]) if message.get("text_key") else message["content"]
            if message["role"] == "assistant":
                render_assistant_message(message, text)
                # Feedback for real answers (with sources)
                if message.get("sources") and index > 0:
                    render_feedback_buttons(index)
            else:
                st.markdown(text)
            if message.get("sources"):
                render_sources(message["sources"])

    if prompt := st.chat_input(t("chat_placeholder")):
        st.session_state.messages.append({"role": "user", "content": prompt, "sources": []})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            message = answer(prompt)
            render_assistant_message(message, message["content"])
            if message["sources"]:
                render_sources(message["sources"])
        st.session_state.messages.append(message)
