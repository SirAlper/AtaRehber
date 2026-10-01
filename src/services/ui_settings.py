"""Texts of the web UI that differ by organization: the assistant's name, the welcome and disclaimer texts, the
example questions, the example request, and the labels of the profile fields.

Admins change them in the web UI; they are stored in UI_SETTINGS_FILE (data directory, so full backups include
it). An empty text keeps the web UI's built-in default. UI_LANGUAGE and UI_DISCLAIMER from the environment set
the default language and a disclaimer for both languages.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.core.config import UI_DISCLAIMER, UI_LANGUAGE, UI_SETTINGS_FILE
from src.core.logger import get_logger

logger = get_logger("UISettings")

LANGUAGES = ("tr", "en")
# Text fields per language and their longest accepted length
TEXT_FIELDS = {
    "welcome": 300,
    "welcome_guest": 300,
    "disclaimer": 300,
    "request_example": 150,
    "unit_label": 60,
    "program_label": 60,
    "level_label": 60,
}
MAX_APP_NAME_LENGTH = 40
MAX_SUGGESTIONS = 6
MAX_SUGGESTION_LENGTH = 150


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Settings with known fields only: texts on one line and cut to their limits, example questions without
    empty lines and repeats."""
    texts_in = data.get("texts") if isinstance(data.get("texts"), dict) else {}
    texts = {}
    for language in LANGUAGES:
        given = texts_in.get(language) if isinstance(texts_in.get(language), dict) else {}
        text = {field: _line(given.get(field), limit) for field, limit in TEXT_FIELDS.items()}
        suggestions = given.get("suggestions") if isinstance(given.get("suggestions"), list) else []
        cleaned = [_line(s, MAX_SUGGESTION_LENGTH) for s in suggestions]
        text["suggestions"] = list(dict.fromkeys(s for s in cleaned if s))[:MAX_SUGGESTIONS]
        texts[language] = text
    return {"app_name": _line(data.get("app_name"), MAX_APP_NAME_LENGTH), "texts": texts}


class UiSettingsStore:
    """Thread-safe JSON store of the UI settings."""

    def __init__(self, path: str = UI_SETTINGS_FILE):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as e:
            logger.error(f"Could not read {self.path}: {e}")
            return {}

    def get(self) -> Dict[str, Any]:
        """The stored settings (normalized), with who changed them last."""
        with self._lock:
            data = self._load()
        settings = normalize_settings(data)
        settings["updated_by"] = str(data.get("updated_by") or "")
        settings["updated_at"] = str(data.get("updated_at") or "")
        return settings

    def save(self, data: Dict[str, Any], author: str) -> Dict[str, Any]:
        settings = normalize_settings(data)
        stored = {**settings, "updated_by": author, "updated_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            temp = f"{self.path}.tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(stored, f, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)
        return stored

    def public(self) -> Dict[str, Any]:
        """What every visitor's web UI gets (before login): the settings and the default language.

        UI_DISCLAIMER fills the disclaimer of a language the admin left empty.
        """
        settings = self.get()
        for language in LANGUAGES:
            if not settings["texts"][language]["disclaimer"]:
                settings["texts"][language]["disclaimer"] = _line(UI_DISCLAIMER, TEXT_FIELDS["disclaimer"])
        return {
            "app_name": settings["app_name"],
            "default_language": default_language(),
            "texts": settings["texts"],
        }


def default_language(value: Optional[str] = None) -> str:
    language = (value if value is not None else UI_LANGUAGE).strip().lower()
    return language if language in LANGUAGES else "tr"


ui_settings_store = UiSettingsStore()
