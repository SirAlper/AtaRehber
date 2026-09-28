"""HTTP client for the backend API. Every call returns plain data or (ok, message) and never raises."""

import os
from typing import Any, Optional, Tuple

import requests
import streamlit as st

from session import auth_headers, store_tokens, t

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _call(method: str, path: str, timeout: float = 10, retry_on_401: bool = True, **kwargs) -> Optional[Any]:
    """Send an authenticated request; refreshes the access token once on HTTP 401. None if unreachable."""
    try:
        response = getattr(requests, method)(f"{API_BASE_URL}{path}", headers=auth_headers(), timeout=timeout, **kwargs)
    except Exception:
        return None
    if response.status_code == 401 and retry_on_401 and refresh_tokens():
        return _call(method, path, timeout=timeout, retry_on_401=False, **kwargs)
    return response


def _json(response, default=None):
    if response is None or response.status_code != 200:
        return default
    try:
        return response.json()
    except ValueError:
        return default


def _detail(response) -> str:
    try:
        body = response.json()
        return body.get("detail") or body.get("message") or response.text
    except ValueError:
        return response.text


def _result(response, ok_status: int = 200, ok_message: str = "") -> Tuple[bool, str]:
    if response is None:
        return False, t("api_offline")
    if response.status_code == ok_status:
        return True, ok_message or _detail(response)
    return False, _detail(response)


def _groups(text: str) -> list:
    return [g.strip() for g in text.split(",") if g.strip()]


# ── Authentication ──


def login(username: str, password: str) -> Tuple[bool, str]:
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/auth/login", json={"username": username, "password": password}, timeout=10
        )
    except Exception as e:
        return False, t("connection_error", error=e)
    if response.status_code == 200:
        store_tokens(response.json())
        return True, t("login_success")
    return False, _detail(response) or t("login_failed")


def guest_access_enabled() -> bool:
    """Whether the backend allows guest sessions (GUEST_ACCESS_ENABLED)."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/auth/guest", timeout=5)
    except Exception:
        return False
    return bool(_json(response, {}).get("enabled"))


def start_guest_session() -> Tuple[bool, str]:
    try:
        response = requests.post(f"{API_BASE_URL}/api/v1/auth/guest", timeout=10)
    except Exception as e:
        return False, t("connection_error", error=e)
    if response.status_code == 200:
        store_tokens(response.json())
        return True, ""
    return False, t("guest_failed", error=_detail(response))


def refresh_tokens() -> bool:
    refresh = st.session_state.get("refresh_token")
    if not refresh:
        return False
    try:
        response = requests.post(f"{API_BASE_URL}/api/v1/auth/refresh", json={"refresh_token": refresh}, timeout=10)
    except Exception:
        return False
    if response.status_code == 200:
        store_tokens(response.json())
        return True
    return False


def change_password(current_password: str, new_password: str) -> Tuple[bool, str]:
    response = _call(
        "post",
        "/api/v1/auth/change-password",
        json={"current_password": current_password, "new_password": new_password},
    )
    if response is not None and response.status_code == 200:
        store_tokens(response.json())
        return True, t("password_changed")
    return False, _detail(response) if response is not None else t("password_change_failed")


# ── System, agents, and questions ──


def get_stats() -> Optional[dict]:
    return _json(_call("get", "/api/v1/stats", timeout=5))


def get_agents(fallback_names) -> list:
    agents = _json(_call("get", "/api/v1/agents", timeout=5), {}).get("agents")
    return agents or [{"name": name, "display_name": name, "description": ""} for name in fallback_names]


def ask(question: str, agent: Optional[str] = None) -> dict:
    payload = {"question": question, "session_id": st.session_state.get("session_id")}
    if agent and agent not in ("auto", "none"):
        payload["agent"] = agent
    response = _call("post", "/api/v1/query", json=payload, timeout=180)
    if response is None:
        return {"status": "error", "answer": t("api_connection_error", error=API_BASE_URL), "sources": []}
    if response.status_code == 200:
        return response.json()
    if response.status_code == 401:
        return {"status": "error", "answer": t("session_expired"), "sources": []}
    if response.status_code == 503:
        return {"status": "error", "answer": t("server_busy"), "sources": []}
    return {"status": "error", "answer": t("api_error", error=_detail(response)), "sources": []}


def send_feedback(question: str, feedback: str, comment: str = "") -> bool:
    response = _call("post", "/api/v1/feedback", json={"question": question, "feedback": feedback, "comment": comment})
    return response is not None and response.status_code == 200


# ── Documents ──


def get_documents() -> list:
    return _json(_call("get", "/api/v1/documents", timeout=5), {}).get("documents", [])


def upload_document(uploaded_file, groups: str = "") -> Tuple[bool, str]:
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
    return _result(_call("post", "/api/v1/upload-file", files=files, data={"groups": groups}, timeout=600))


def delete_document(filename: str) -> Tuple[bool, str]:
    return _result(_call("delete", f"/api/v1/documents/{filename}"), ok_message=t("deleted"))


def set_document_access(filename: str, groups: str) -> Tuple[bool, str]:
    response = _call("put", f"/api/v1/documents/{filename}/access", json={"groups": _groups(groups)}, timeout=30)
    return _result(response, ok_message=t("access_saved"))


# ── Service requests ──


def get_requests(all_users: bool = False) -> dict:
    params = {"all_users": str(all_users).lower(), "limit": 30}
    return _json(_call("get", "/api/v1/requests", params=params, timeout=5), {"requests": [], "categories": []})


def create_request(category: str, title: str, description: str) -> Tuple[bool, str]:
    response = _call(
        "post", "/api/v1/requests", json={"category": category, "title": title, "description": description}, timeout=30
    )
    if response is not None and response.status_code == 201:
        return True, t("request_created_toast", id=response.json()["request"]["id"])
    return _result(response, ok_status=201)


def update_request(request_id: int, status: str, note: str = "") -> Tuple[bool, str]:
    response = _call("patch", f"/api/v1/requests/{request_id}", json={"status": status, "resolution_note": note})
    return _result(response, ok_message=t("request_updated"))


# ── Administration ──


def get_users() -> list:
    return _json(_call("get", "/api/v1/auth/users", timeout=5), [])


def set_user_groups(username: str, groups: str) -> Tuple[bool, str]:
    response = _call("patch", f"/api/v1/auth/users/{username}", json={"groups": _groups(groups)})
    return _result(response, ok_message=t("user_groups_saved"))


def get_custom_agents() -> list:
    return _json(_call("get", "/api/v1/admin/custom-agents", timeout=5), {}).get("agents", [])


def get_agent_tools() -> list:
    params = {"language": st.session_state.ui_language}
    return _json(_call("get", "/api/v1/admin/agent-tools", params=params, timeout=5), {}).get("tools", [])


def save_custom_agent(agent: dict) -> Tuple[bool, str]:
    response = _call("put", f"/api/v1/admin/custom-agents/{agent['name']}", json=agent)
    if response is not None and response.status_code == 422:
        # Pydantic lists every invalid field; show their messages
        try:
            errors = response.json().get("detail", [])
            return False, "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in errors)
        except (ValueError, KeyError, TypeError, IndexError):
            pass
    return _result(response, ok_message=t("custom_agent_saved", name=agent["display_name"]))


def delete_custom_agent(name: str) -> Tuple[bool, str]:
    return _result(_call("delete", f"/api/v1/admin/custom-agents/{name}"), ok_message=t("custom_agent_deleted"))


def get_database_status() -> Optional[dict]:
    return _json(_call("get", "/api/v1/database/status", timeout=5))


def sync_table(table_name: str) -> Tuple[bool, str]:
    return _result(_call("post", "/api/v1/database/sync-table", json={"table_name": table_name}, timeout=60))


def get_audit_logs(limit: int = 20) -> list:
    return _json(_call("get", "/api/v1/admin/audit-logs", params={"limit": limit}, timeout=5), {}).get("logs", [])


def get_audit_stats() -> Optional[dict]:
    return _json(_call("get", "/api/v1/admin/audit-stats", timeout=5))
