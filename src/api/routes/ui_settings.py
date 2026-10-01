"""Web UI texts per organization: read by every visitor, changed by admins."""

from typing import Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.auth.dependencies import require_role
from src.auth.models import User
from src.core.audit import audit_logger
from src.services.ui_settings import (
    MAX_APP_NAME_LENGTH,
    MAX_SUGGESTION_LENGTH,
    MAX_SUGGESTIONS,
    TEXT_FIELDS,
    ui_settings_store,
)

router = APIRouter(tags=["UI Settings"])


class LanguageTexts(BaseModel):
    welcome: str = Field("", max_length=TEXT_FIELDS["welcome"])
    welcome_guest: str = Field("", max_length=TEXT_FIELDS["welcome_guest"])
    disclaimer: str = Field("", max_length=TEXT_FIELDS["disclaimer"])
    request_example: str = Field("", max_length=TEXT_FIELDS["request_example"])
    unit_label: str = Field("", max_length=TEXT_FIELDS["unit_label"])
    program_label: str = Field("", max_length=TEXT_FIELDS["program_label"])
    level_label: str = Field("", max_length=TEXT_FIELDS["level_label"])
    suggestions: List[str] = Field(
        default_factory=list,
        max_length=MAX_SUGGESTIONS,
        description=f"Example questions on the empty chat (at most {MAX_SUGGESTIONS}, {MAX_SUGGESTION_LENGTH} "
        "characters each)",
    )


class UiSettings(BaseModel):
    app_name: str = Field("", max_length=MAX_APP_NAME_LENGTH, description="Empty: the built-in name")
    texts: Dict[str, LanguageTexts] = Field(default_factory=dict, description='Keys "tr" and "en"')


@router.get("/api/v1/ui-settings", summary="Web UI Texts")
async def public_ui_settings():
    """Name, texts, and default language of the web UI. Needs no login: the login page shows the name too.
    Empty texts mean the web UI's built-in defaults."""
    return ui_settings_store.public()


@router.get("/api/v1/admin/ui-settings", summary="Stored Web UI Texts")
async def get_ui_settings(_: User = Depends(require_role("admin"))):
    return ui_settings_store.get()


@router.put("/api/v1/admin/ui-settings", summary="Change Web UI Texts")
async def update_ui_settings(body: UiSettings, current_user: User = Depends(require_role("admin"))):
    stored = ui_settings_store.save(body.model_dump(), current_user.username)
    await audit_logger.alog(
        username=current_user.username,
        role=current_user.role,
        action="ui_settings",
        detail="Changed the web UI texts",
        status="success",
    )
    return stored
