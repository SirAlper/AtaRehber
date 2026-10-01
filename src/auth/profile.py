"""User profile: where in the organization a user belongs, so agents can answer for them.

Rules often differ by unit, program, or level ("in the Faculty of Engineering", "for graduate students"). An admin
records these for each account; agents add them to their prompts, so "how many absences are allowed in my
department?" is answered for the user's department instead of being guessed.
"""

from typing import Dict, Optional

# unit: faculty, school, directorate; program: department or program; level: class year, degree, grade
PROFILE_FIELDS = ("unit", "program", "level")
MAX_PROFILE_VALUE_LENGTH = 100


def normalize_profile(profile: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Known fields with their whitespace collapsed; empty values are dropped. Raises ValueError on unknown fields
    or values that are too long."""
    if not profile:
        return {}
    unknown = sorted(set(profile) - set(PROFILE_FIELDS))
    if unknown:
        raise ValueError(f"Unknown profile field(s): {', '.join(unknown)}. Use {', '.join(PROFILE_FIELDS)}.")
    cleaned = {}
    for field in PROFILE_FIELDS:
        value = " ".join(str(profile.get(field) or "").split())
        if len(value) > MAX_PROFILE_VALUE_LENGTH:
            raise ValueError(f"Profile field '{field}' is longer than {MAX_PROFILE_VALUE_LENGTH} characters.")
        if value:
            cleaned[field] = value
    return cleaned


def profile_note(user: Optional[Dict]) -> str:
    """Prompt line about the asking user, or "" when nothing is known about them."""
    profile = (user or {}).get("profile") or {}
    parts = [f"{field}: {profile[field]}" for field in PROFILE_FIELDS if profile.get(field)]
    if not parts:
        return ""
    return (
        f"About the asking user: {'; '.join(parts)}. When the rules differ by unit, program, or level, answer for "
        "this user and say which one you applied. Questions about 'my department', 'my faculty', or 'my program' "
        "refer to these."
    )
