import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
import bcrypt

from src.auth.models import User, UserResponse, UserRole
from src.core.config import (
    USERS_FILE_PATH,
    ADMIN_DEFAULT_USERNAME,
    ADMIN_DEFAULT_PASSWORD,
    INSECURE_DEFAULT_PASSWORD,
)
from src.core.logger import get_logger

logger = get_logger("Auth.UserStore")


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


class UserStore:
    """
    Thread-safe JSON-backed enterprise user store.
    Handles user CRUD, password hashing, and default admin seeding.
    Uses RLock to safely support nested locking (e.g., authenticate_user → get_user).
    """

    def __init__(self, file_path: str = USERS_FILE_PATH):
        self.file_path = file_path
        self._lock = threading.RLock()
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create file and seed default admin if storage does not exist."""
        with self._lock:
            dir_name = os.path.dirname(os.path.abspath(self.file_path))
            os.makedirs(dir_name, exist_ok=True)

            if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
                admin_user = User(
                    username=ADMIN_DEFAULT_USERNAME,
                    role="admin",
                    hashed_password=hash_password(ADMIN_DEFAULT_PASSWORD),
                    disabled=False,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    must_change_password=ADMIN_DEFAULT_PASSWORD == INSECURE_DEFAULT_PASSWORD,
                )
                initial_data: Dict[str, dict] = {admin_user.username: admin_user.model_dump()}
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, indent=2)
                logger.info(f"Initialized user store at {self.file_path} with default admin '{ADMIN_DEFAULT_USERNAME}'")

            if ADMIN_DEFAULT_PASSWORD == INSECURE_DEFAULT_PASSWORD:
                logger.warning(
                    "SECURITY WARNING: Default admin password 'admin123' is configured! "
                    "The admin must change it on first login; set ADMIN_DEFAULT_PASSWORD in your .env for production."
                )

    def _load_data(self) -> Dict[str, dict]:
        """Read users dictionary from JSON file."""
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading users from {self.file_path}: {e}")
            return {}

    def _save_data(self, data: Dict[str, dict]) -> None:
        """Atomic write users dictionary to JSON file."""
        temp_file = f"{self.file_path}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"Error saving users to {self.file_path}: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise

    def get_user(self, username: str) -> Optional[User]:
        """Retrieve user by username."""
        with self._lock:
            data = self._load_data()
            user_dict = data.get(username)
            if user_dict:
                return User(**user_dict)
            return None

    def list_users(self) -> List[UserResponse]:
        """List all users without exposing password hashes."""
        with self._lock:
            data = self._load_data()
            users: List[UserResponse] = []
            for u in data.values():
                users.append(
                    UserResponse(
                        username=u["username"],
                        role=u["role"],
                        disabled=u.get("disabled", False),
                        created_at=u.get("created_at"),
                        must_change_password=u.get("must_change_password", False),
                    )
                )
            return users

    def create_user(self, username: str, password: str, role: UserRole) -> User:
        """Create a new user with hashed password after validating password policy."""
        from src.auth.password_policy import password_policy

        violations = password_policy.validate(password)
        if violations:
            raise ValueError(f"Password does not meet policy requirements: {'; '.join(violations)}")

        with self._lock:
            data = self._load_data()
            if username in data:
                raise ValueError(f"User '{username}' already exists.")

            new_user = User(
                username=username,
                role=role,
                hashed_password=hash_password(password),
                disabled=False,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            data[username] = new_user.model_dump()
            self._save_data(data)
            logger.info(f"User '{username}' registered with role '{role}'.")
            return new_user

    def update_user(
        self,
        username: str,
        password: Optional[str] = None,
        role: Optional[UserRole] = None,
        disabled: Optional[bool] = None,
        must_change_password: Optional[bool] = None,
    ) -> Optional[User]:
        """Update existing user properties.

        Password changes are validated against the password policy and revoke all
        previously issued tokens (as does disabling the account).
        """
        from src.auth.password_policy import password_policy

        if password is not None:
            violations = password_policy.validate(password)
            if violations:
                raise ValueError(f"Password does not meet policy requirements: {'; '.join(violations)}")

        with self._lock:
            data = self._load_data()
            if username not in data:
                return None

            user_data = data[username]
            revoke_tokens = False
            if password is not None:
                user_data["hashed_password"] = hash_password(password)
                revoke_tokens = True
            if role is not None:
                user_data["role"] = role
            if disabled is not None:
                if disabled and not user_data.get("disabled", False):
                    revoke_tokens = True
                user_data["disabled"] = disabled
            if must_change_password is not None:
                user_data["must_change_password"] = must_change_password
            if revoke_tokens:
                user_data["token_version"] = int(user_data.get("token_version", 0)) + 1

            data[username] = user_data
            self._save_data(data)
            logger.info(f"User '{username}' updated.")
            return User(**user_data)

    def delete_user(self, username: str) -> bool:
        """Delete a user. Prevents deleting the primary default admin."""
        if username == ADMIN_DEFAULT_USERNAME:
            raise ValueError("Default primary admin user cannot be deleted.")

        with self._lock:
            data = self._load_data()
            if username not in data:
                return False

            del data[username]
            self._save_data(data)
            logger.info(f"User '{username}' deleted.")
            return True

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Verify username and password, checking if disabled."""
        user = self.get_user(username)
        if not user:
            return None
        if user.disabled:
            logger.warning(f"Authentication rejected for disabled user '{username}'")
            return None
        if not verify_password(password, user.hashed_password):
            logger.warning(f"Failed authentication attempt for user '{username}'")
            return None
        return user


# Singleton instance
user_store = UserStore()
