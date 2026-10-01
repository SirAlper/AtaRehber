import os
import re
from typing import List
from src.core.logger import get_logger

logger = get_logger("Auth.PasswordPolicy")


class PasswordPolicy:
    """Configurable password strength policy for enterprise user management.

    All settings are driven by environment variables with sensible defaults:
        PASSWORD_MIN_LENGTH (default: 8)
        PASSWORD_REQUIRE_UPPERCASE (default: true)
        PASSWORD_REQUIRE_LOWERCASE (default: true)
        PASSWORD_REQUIRE_DIGIT (default: true)
        PASSWORD_REQUIRE_SPECIAL (default: false)
    """

    def __init__(self):
        self.min_length = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
        self.require_uppercase = os.getenv("PASSWORD_REQUIRE_UPPERCASE", "true").lower() == "true"
        self.require_lowercase = os.getenv("PASSWORD_REQUIRE_LOWERCASE", "true").lower() == "true"
        self.require_digit = os.getenv("PASSWORD_REQUIRE_DIGIT", "true").lower() == "true"
        self.require_special = os.getenv("PASSWORD_REQUIRE_SPECIAL", "false").lower() == "true"

    def validate(self, password: str) -> List[str]:
        """Validate password against configured policy. Returns list of violation messages (empty = valid)."""
        violations: List[str] = []

        if len(password) < self.min_length:
            violations.append(f"Password must be at least {self.min_length} characters long.")

        if self.require_uppercase and not re.search(r"[A-Z]", password):
            violations.append("Password must contain at least one uppercase letter (A-Z).")

        if self.require_lowercase and not re.search(r"[a-z]", password):
            violations.append("Password must contain at least one lowercase letter (a-z).")

        if self.require_digit and not re.search(r"\d", password):
            violations.append("Password must contain at least one digit (0-9).")

        if self.require_special and not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
            violations.append("Password must contain at least one special character.")

        return violations


# Singleton instance
password_policy = PasswordPolicy()
