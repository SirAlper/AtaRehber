"""Streamlit UI: Turkish/English texts, disclaimer, and page numbers in sources.

The app runs headless with streamlit.testing.AppTest; HTTP calls to the backend are mocked.
"""

import os
import string
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from ui.i18n import TEXTS, page_label, translate  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.py")


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_text_exists_in_both_languages_with_the_same_placeholders():
    for key, variants in TEXTS.items():
        assert set(variants) == {"tr", "en"}, key
        assert placeholders(variants["tr"]) == placeholders(variants["en"]), key


def test_page_labels():
    assert page_label("tr", {"page": 4}) == "s. 4"
    assert page_label("tr", {"page": 4, "page_end": 5}) == "s. 4–5"
    assert page_label("en", {"page": 4, "page_end": 5}) == "pp. 4–5"
    assert page_label("tr", {"source": "notes.txt"}) == ""


def test_custom_disclaimer_overrides_every_language():
    with patch("ui.i18n.CUSTOM_DISCLAIMER", "Resmî bilgi için Öğrenci İşleri'ne başvurun."):
        assert translate("en", "disclaimer") == "Resmî bilgi için Öğrenci İşleri'ne başvurun."


def all_text(at):
    parts = [m.value for m in at.markdown] + [m.value for m in at.info] + [m.value for m in at.caption]
    parts += [m.value for m in at.sidebar.markdown] + [m.value for m in at.title] + [m.value for m in at.sidebar.title]
    parts += [b.label for b in at.sidebar.button]
    return "\n".join(str(p) for p in parts)


def test_login_screen_is_turkish_by_default_and_switches_to_english():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    text = all_text(at)
    assert "Giriş gerekli" in text
    assert "Giriş Yap" in text

    at.sidebar.selectbox[0].set_value("en").run()
    text = all_text(at)
    assert "Authentication Required" in text
    assert "Log In" in text


def fake_response(payload, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    return response


def fake_get(url, **kwargs):
    if url.endswith("/api/v1/stats"):
        return fake_response(
            {"llm_model": "qwen2.5:7b", "llm_status": "ok", "device": "CPU", "total_documents": 1, "total_chunks": 3}
        )
    if url.endswith("/api/v1/agents"):
        return fake_response({"agents": [{"name": "auto", "display_name": "Auto", "description": ""}]})
    if url.endswith("/api/v1/documents"):
        return fake_response({"documents": []})
    return fake_response({}, status=404)


def test_logged_in_chat_shows_disclaimer_and_page_numbers():
    answer = {
        "answer": "Yıllık izin 20 iş günüdür.",
        "active_agent": "doc_agent",
        "hallucination_grade": "yes",
        "is_refined": False,
        "agent_trace": [],
        "sources": [
            {
                "source": "yonetmelik.pdf",
                "chunk_index": 2,
                "page": 4,
                "page_end": 5,
                "reranker_score": 0.98,
                "content": "Madde 12 - Yıllık izin 20 iş günüdür.",
            }
        ],
    }
    with (
        patch("requests.get", side_effect=fake_get),
        patch("requests.post", return_value=fake_response(answer)),
    ):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["auth_token"] = "token"
        at.session_state["user_info"] = {"username": "ogrenci", "role": "viewer"}
        at.run()
        assert "yapay zekâ tarafından üretilir" in all_text(at)

        at.chat_input[0].set_value("Yıllık izin kaç gün?").run()

    assert not at.exception
    text = all_text(at)
    assert "Yıllık izin 20 iş günüdür." in text
    assert "`yonetmelik.pdf` — s. 4–5" in text
    assert "Doküman Ajanı" in text
