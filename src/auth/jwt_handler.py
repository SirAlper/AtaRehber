import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt

from src.auth.models import TokenData
from src.core.config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    JWT_SECRET_FILE_PATH,
)
from src.core.logger import get_logger

logger = get_logger("Auth.JWT")


def get_jwt_secret() -> str:
    """
    Retrieve JWT secret key from environment or persisted file.
    Generates a secure random 256-bit secret if not present.
    """
    if JWT_SECRET_KEY and JWT_SECRET_KEY.strip():
        return JWT_SECRET_KEY.strip()

    # Try reading from secret file
    if os.path.exists(JWT_SECRET_FILE_PATH):
        try:
            with open(JWT_SECRET_FILE_PATH, "r", encoding="utf-8") as f:
                stored_secret = f.read().strip()
                if stored_secret:
                    return stored_secret
        except (IOError, PermissionError) as e:
            logger.warning(f"Could not read JWT secret file: {e}")

    # Generate and persist new secret
    new_secret = secrets.token_urlsafe(32)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(JWT_SECRET_FILE_PATH)), exist_ok=True)
        # Create with owner-only permissions (0600) on POSIX; the mode is ignored on Windows
        fd = os.open(JWT_SECRET_FILE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_secret)
        logger.info(f"Generated new persistent JWT secret at {JWT_SECRET_FILE_PATH}")
    except (IOError, PermissionError, OSError) as e:
        logger.warning(f"Failed to persist JWT secret to file: {e}")

    return new_secret


_SECRET = get_jwt_secret()


def create_access_token(
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
    token_version: int = 0,
) -> tuple[str, int]:
    """
    Generate signed JWT access token.
    Returns (token_str, expires_in_seconds).
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
        expires_in = int(expires_delta.total_seconds())
    else:
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": username,
        "role": role,
        "type": "access",
        "ver": token_version,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt, expires_in


def create_refresh_token(username: str, role: str, token_version: int = 0) -> tuple[str, int]:
    """
    Generate signed JWT refresh token with longer expiry.
    Returns (token_str, expires_in_seconds).
    """
    expires_in = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": username,
        "role": role,
        "type": "refresh",
        "ver": token_version,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt, expires_in


def _decode_token(token: str, expected_type: str) -> Optional[TokenData]:
    """Verify signature/expiry and require the token's 'type' claim to match expected_type."""
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug(f"{expected_type.capitalize()} token has expired")
        return None
    except jwt.PyJWTError as e:
        logger.debug(f"Invalid {expected_type} token: {e}")
        return None

    username = payload.get("sub")
    role = payload.get("role")
    token_type = payload.get("type")
    if not username or not role or token_type != expected_type:
        return None
    try:
        token_version = int(payload.get("ver", 0))
    except (TypeError, ValueError):
        return None
    return TokenData(
        username=username,
        role=role,
        exp=payload.get("exp"),
        token_type=token_type,
        token_version=token_version,
    )


def decode_access_token(token: str) -> Optional[TokenData]:
    """
    Verify and decode JWT access token. Returns TokenData or None if invalid/expired.
    Refresh tokens are rejected so they cannot be used as bearer credentials.
    """
    return _decode_token(token, "access")


def decode_refresh_token(token: str) -> Optional[TokenData]:
    """
    Verify and decode JWT refresh token. Returns TokenData or None if invalid/expired.
    Only accepts tokens with type='refresh'.
    """
    return _decode_token(token, "refresh")
