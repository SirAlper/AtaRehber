"""Authentication and Access Control API Routes.

Exposes endpoints for user authentication (JWT), token refresh,
profile retrieval, and administrative user management with compliance audit logging.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_authenticated_user, require_role
from src.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from src.auth.login_throttle import login_throttle
from src.auth.models import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    User,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from src.auth.user_store import user_store, verify_password
from src.core.config import INSECURE_DEFAULT_PASSWORD
from src.core.audit import audit_logger
from src.core.logger import get_logger

logger = get_logger("API.Auth")
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Access Control"])


def _issue_tokens(user: User) -> TokenResponse:
    access_token, expires_in = create_access_token(user.username, user.role, token_version=user.token_version)
    refresh_token, _ = create_refresh_token(user.username, user.role, token_version=user.token_version)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        role=user.role,
        username=user.username,
        expires_in=expires_in,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest, http_req: Request):
    """Authenticate with username and password to obtain JWT access and refresh tokens."""
    ip_addr = http_req.client.host if http_req.client else None

    retry_after = login_throttle.retry_after(credentials.username)
    if retry_after:
        await audit_logger.alog(
            username=credentials.username,
            role="unknown",
            action="login",
            detail="Login blocked (too many failed attempts)",
            ip_address=ip_addr,
            status="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = user_store.authenticate_user(credentials.username, credentials.password)
    if not user:
        login_throttle.record_failure(credentials.username)
        await audit_logger.alog(
            username=credentials.username,
            role="unknown",
            action="login",
            detail="Failed login attempt (invalid credentials)",
            ip_address=ip_addr,
            status="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_throttle.reset(credentials.username)

    # Accounts still using the built-in default password must change it before using the API
    if credentials.password == INSECURE_DEFAULT_PASSWORD and not user.must_change_password:
        user = user_store.update_user(user.username, must_change_password=True) or user

    await audit_logger.alog(
        username=user.username,
        role=user.role,
        action="login",
        detail="Successful authentication" + (" (password change required)" if user.must_change_password else ""),
        ip_address=ip_addr,
        status="success",
    )
    logger.info(f"User '{user.username}' logged in successfully (role: {user.role}).")
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest, http_req: Request):
    """Exchange a valid refresh token for a new access token without re-authentication."""
    ip_addr = http_req.client.host if http_req.client else None
    token_data = decode_refresh_token(request.refresh_token)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_store.get_user(token_data.username)
    if user is None or user.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is no longer active.",
        )
    if token_data.token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked. Please log in again.",
        )

    await audit_logger.alog(
        username=user.username,
        role=user.role,
        action="token_refresh",
        detail="Access token refreshed",
        ip_address=ip_addr,
        status="success",
    )
    return _issue_tokens(user)


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: User = Depends(get_authenticated_user)):
    """Get profile information of currently authenticated user."""
    return UserResponse(
        username=current_user.username,
        role=current_user.role,
        disabled=current_user.disabled,
        created_at=current_user.created_at,
        must_change_password=current_user.must_change_password,
    )


@router.post("/change-password", response_model=TokenResponse)
async def change_my_password(
    request: ChangePasswordRequest,
    http_req: Request,
    current_user: User = Depends(get_authenticated_user),
):
    """Change the caller's own password. Revokes all existing tokens and returns fresh ones."""
    ip_addr = http_req.client.host if http_req.client else None
    if not verify_password(request.current_password, current_user.hashed_password):
        await audit_logger.alog(
            username=current_user.username,
            role=current_user.role,
            action="change_password",
            detail="Rejected (current password incorrect)",
            ip_address=ip_addr,
            status="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if request.new_password in (request.current_password, INSECURE_DEFAULT_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current and default passwords.",
        )

    try:
        updated = user_store.update_user(
            current_user.username,
            password=request.new_password,
            must_change_password=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    await audit_logger.alog(
        username=updated.username,
        role=updated.role,
        action="change_password",
        detail="Password changed; existing tokens revoked",
        ip_address=ip_addr,
        status="success",
    )
    return _issue_tokens(updated)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    new_user_data: UserCreate,
    current_admin: User = Depends(require_role("admin")),
):
    """Register a new user (Admin only). Password must meet configured policy requirements."""
    try:
        created = user_store.create_user(
            username=new_user_data.username,
            password=new_user_data.password,
            role=new_user_data.role,
        )
        await audit_logger.alog(
            username=current_admin.username,
            role=current_admin.role,
            action="register_user",
            detail=f"Created user '{created.username}' with role '{created.role}'",
            status="success",
        )
        return UserResponse(
            username=created.username,
            role=created.role,
            disabled=created.disabled,
            created_at=created.created_at,
        )
    except ValueError as e:
        await audit_logger.alog(
            username=current_admin.username,
            role=current_admin.role,
            action="register_user",
            detail=f"Failed to create user '{new_user_data.username}': {e}",
            status="error",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/users", response_model=List[UserResponse])
async def list_all_users(_: User = Depends(require_role("admin"))):
    """List all registered users (Admin only)."""
    return user_store.list_users()


@router.patch("/users/{username}", response_model=UserResponse)
async def update_user(
    username: str,
    update_data: UserUpdate,
    current_admin: User = Depends(require_role("admin")),
):
    """Update user status, role, or reset password (Admin only)."""
    try:
        updated = user_store.update_user(
            username=username,
            password=update_data.password,
            role=update_data.role,
            disabled=update_data.disabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )
    await audit_logger.alog(
        username=current_admin.username,
        role=current_admin.role,
        action="update_user",
        detail=f"Updated user '{username}' (role: {updated.role}, disabled: {updated.disabled})",
        status="success",
    )
    return UserResponse(
        username=updated.username,
        role=updated.role,
        disabled=updated.disabled,
        created_at=updated.created_at,
    )


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    current_admin: User = Depends(require_role("admin")),
):
    """Delete a user account (Admin only)."""
    try:
        success = user_store.delete_user(username)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{username}' not found.",
            )
        await audit_logger.alog(
            username=current_admin.username,
            role=current_admin.role,
            action="delete_user",
            detail=f"Deleted user '{username}'",
            status="success",
        )
        return {"status": "success", "message": f"User '{username}' deleted."}
    except ValueError as e:
        await audit_logger.alog(
            username=current_admin.username,
            role=current_admin.role,
            action="delete_user",
            detail=f"Failed to delete user '{username}': {e}",
            status="error",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
