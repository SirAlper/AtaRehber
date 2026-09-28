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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(REPO_ROOT, "ui", "app.py")


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


def test_forced_password_change_sends_all_fields_and_names_empty_ones():
    tokens = {"access_token": "t", "refresh_token": "r", "role": "admin", "username": "admin", "expires_in": 900}
    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return fake_response(dict(tokens, must_change_password=False))

    with patch("requests.get", side_effect=fake_get), patch("requests.post", side_effect=fake_post):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["auth_token"] = "token"
        at.session_state["user_info"] = {"username": "admin", "role": "admin"}
        at.session_state["must_change_password"] = True
        at.run()

        # The current password is missing: the warning names it and nothing is sent
        at.sidebar.text_input(key="cp_new").set_value("YeniSifre!2026")
        at.sidebar.text_input(key="cp_confirm").set_value("YeniSifre!2026")
        next(b for b in at.sidebar.button if b.label == "Şifreyi Güncelle").click().run()
        assert any("Boş alan: Mevcut şifre" in w.value for w in at.sidebar.warning)
        assert posts == []

        at.sidebar.text_input(key="cp_current").set_value("admin123")
        next(b for b in at.sidebar.button if b.label == "Şifreyi Güncelle").click().run()

    assert not at.exception
    assert posts == [
        (
            "http://127.0.0.1:8000/api/v1/auth/change-password",
            {"current_password": "admin123", "new_password": "YeniSifre!2026"},
        )
    ]
    assert at.session_state["must_change_password"] is False


def test_guest_session_shows_only_the_chat_and_reports_a_busy_server():
    def guest_get(url, **kwargs):
        if url.endswith("/api/v1/auth/guest"):
            return fake_response({"enabled": True})
        return fake_get(url, **kwargs)

    guest_token = {"access_token": "g", "role": "guest", "username": "guest-1a2b", "expires_in": 7200}
    replies = {
        "/api/v1/auth/guest": fake_response(guest_token),
        "/api/v1/query": fake_response({"detail": "busy"}, 503),
    }

    with (
        patch("requests.get", side_effect=guest_get),
        patch("requests.post", side_effect=lambda url, **kwargs: replies[url.split("8000")[1]]),
    ):
        at = AppTest.from_file(APP, default_timeout=30).run()
        next(b for b in at.sidebar.button if b.label == "👋 Misafir olarak devam et").click().run()
        assert not at.exception
        text = all_text(at)
        assert "Misafir" in text
        assert "Ziyaretçilerle paylaşılan belgelerle ilgili" in text
        # No system details, agent choice, documents, or requests for guests
        assert "Doküman Yükle" not in text and not at.sidebar.selectbox[1:]

        at.chat_input[0].set_value("Kayıt yenileme ne zaman?").run()

    assert "Asistan şu anda çok yoğun" in all_text(at)


def test_admin_creates_a_custom_agent_with_tools():
    tools = [
        {"name": "documents", "label": "📄 Belge arama", "description": "Belgeler", "available": True},
        {"name": "calculator", "label": "🧮 Hesap makinesi", "description": "Hesap", "available": True},
    ]
    existing = {
        "name": "aof_asistani",
        "display_name": "AÖF Asistanı",
        "description": "Açıköğretim kayıt ve sınav soruları",
        "instructions": "Açıköğretim sorularını yanıtla.",
        "tools": ["documents"],
        "enabled": True,
        "available": True,
    }

    def admin_get(url, **kwargs):
        if url.endswith("/api/v1/admin/agent-tools"):
            return fake_response({"tools": tools})
        if url.endswith("/api/v1/admin/custom-agents"):
            return fake_response({"agents": [existing]})
        return fake_get(url, **kwargs)

    saved = []

    def fake_put(url, **kwargs):
        saved.append((url, kwargs.get("json")))
        return fake_response({"status": "success"})

    with (
        patch("requests.get", side_effect=admin_get),
        patch("requests.put", side_effect=fake_put),
        patch("requests.post", return_value=fake_response({})),
        patch("requests.patch", return_value=fake_response({})),
    ):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["auth_token"] = "token"
        at.session_state["user_info"] = {"username": "admin", "role": "admin"}
        at.run()
        assert not at.exception
        assert "**AÖF Asistanı** (`aof_asistani`) · 🟢 etkin" in all_text(at)

        inputs = {ti.label: ti for ti in at.sidebar.text_input}
        areas = {ta.label: ta for ta in at.sidebar.text_area}
        inputs["Sistem adı"].set_value("not_asistani")
        # The last "Görünen ad" field belongs to the new-agent form (the edit form comes first)
        [ti for ti in at.sidebar.text_input if ti.label == "Görünen ad"][-1].set_value("Not Asistanı")
        [ta for ta in at.sidebar.text_area if ta.label == "Hangi işler için çalışır?"][-1].set_value(
            "Not ortalaması ve harf notu hesaplama soruları"
        )
        [ta for ta in at.sidebar.text_area if ta.label == "Talimat (prompt)"][-1].set_value(
            "Vize ve final notlarından ortalamayı hesapla."
        )
        [ms for ms in at.sidebar.multiselect if ms.label == "Araçlar"][-1].set_value(["🧮 Hesap makinesi"])
        assert areas  # text areas were found
        next(b for b in reversed(at.sidebar.button) if b.label == "Ajanı oluştur").click().run()

    assert not at.exception
    assert saved == [
        (
            "http://127.0.0.1:8000/api/v1/admin/custom-agents/not_asistani",
            {
                "name": "not_asistani",
                "display_name": "Not Asistanı",
                "description": "Not ortalaması ve harf notu hesaplama soruları",
                "instructions": "Vize ve final notlarından ortalamayı hesapla.",
                "tools": ["calculator"],
                "enabled": True,
            },
        )
    ]
