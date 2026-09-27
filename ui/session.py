"""Streamlit session state: login tokens, conversation, and texts in the selected language."""

import uuid

import streamlit as st

from i18n import DEFAULT_UI_LANGUAGE, translate

_DEFAULTS = {
    "ui_language": DEFAULT_UI_LANGUAGE,
    "auth_token": None,
    "refresh_token": None,
    "user_info": None,
    "must_change_password": False,
    "selected_agent": "auto",
}


def init_session_state() -> None:
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:12]
    if "messages" not in st.session_state:
        # Fixed assistant texts are stored as keys, so they follow a later language switch
        st.session_state.messages = [
            {"role": "assistant", "text_key": "welcome", "sources": [], "active_agent": "supervisor"}
        ]


def t(key: str, **values) -> str:
    """Text in the language selected in the sidebar."""
    return translate(st.session_state.ui_language, key, **values)


def user_role() -> str:
    return (st.session_state.user_info or {}).get("role", "viewer")


def is_logged_in() -> bool:
    return bool(st.session_state.get("auth_token"))


def is_password_change_pending() -> bool:
    return is_logged_in() and st.session_state.get("must_change_password", False)


def store_tokens(data: dict) -> None:
    """Keep a TokenResponse from login, refresh, or change-password in the session."""
    st.session_state.auth_token = data["access_token"]
    st.session_state.refresh_token = data.get("refresh_token", st.session_state.get("refresh_token"))
    st.session_state.user_info = {"username": data["username"], "role": data["role"]}
    st.session_state.must_change_password = data.get("must_change_password", False)


def auth_headers() -> dict:
    token = st.session_state.get("auth_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def logout() -> None:
    st.session_state.auth_token = None
    st.session_state.refresh_token = None
    st.session_state.user_info = None
    st.session_state.must_change_password = False
    st.rerun()


def new_conversation() -> None:
    st.session_state.session_id = uuid.uuid4().hex[:12]
    st.session_state.messages = [{"role": "assistant", "text_key": "conversation_cleared", "sources": []}]
