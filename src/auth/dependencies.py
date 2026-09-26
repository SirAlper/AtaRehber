from typing import Callable
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.jwt_handler import decode_access_token
from src.auth.models import User
from src.auth.user_store import user_store
from src.core.config import REQUIRE_DEFAULT_PASSWORD_CHANGE
from src.core.logger import get_logger

logger = get_logger("Auth.Dependencies")

# Use HTTPBearer with auto_error=False to provide clear, custom error responses
security = HTTPBearer(auto_error=False)

PASSWORD_CHANGE_REQUIRED_DETAIL = "Password change required. Use /api/v1/auth/change-password before continuing."


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> User:
    """
    FastAPI dependency to extract and validate the JWT Bearer token.
    Returns the authenticated User model without enforcing a pending password change,
    so it is only suitable for the profile and change-password endpoints.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    token_data = decode_access_token(token)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_store.get_user(token_data.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token_data.token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


async def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    """
    FastAPI dependency returning the authenticated user.
    Blocks accounts that must replace an insecure default password first.
    """
    if REQUIRE_DEFAULT_PASSWORD_CHANGE and user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_DETAIL,
        )
    return user


def require_role(*allowed_roles: str) -> Callable:
    """
    Dependency factory that enforces Role-Based Access Control (RBAC).
    Allowed roles can be e.g. ("admin",), ("admin", "editor"), ("admin", "editor", "viewer").
    """

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                f"Access denied for user '{current_user.username}' (role: {current_user.role}). "
                f"Required roles: {allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(allowed_roles)}.",
            )
        return current_user

    return role_checker
