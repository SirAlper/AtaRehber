from typing import List, Literal, Optional
from pydantic import BaseModel, Field


UserRole = Literal["admin", "editor", "viewer"]


class User(BaseModel):
    username: str
    role: UserRole
    hashed_password: str
    disabled: bool = False
    created_at: Optional[str] = None
    # Incremented whenever credentials change; tokens carrying an older version are rejected
    token_version: int = 0
    must_change_password: bool = False
    # Groups for document-level access control (e.g. "akademik", "idari"); see src/auth/document_access.py
    groups: List[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    username: str
    role: UserRole
    disabled: bool = False
    created_at: Optional[str] = None
    must_change_password: bool = False
    groups: List[str] = Field(default_factory=list)

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            username=user.username,
            role=user.role,
            disabled=user.disabled,
            created_at=user.created_at,
            must_change_password=user.must_change_password,
            groups=user.groups,
        )


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Alphanumeric username")
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Password (validated against the password policy)",
    )
    role: UserRole = "viewer"
    groups: List[str] = Field(default_factory=list, description="Document access groups, e.g. ['akademik']")


class UserUpdate(BaseModel):
    password: Optional[str] = Field(None, min_length=1, max_length=128)
    role: Optional[UserRole] = None
    disabled: Optional[bool] = None
    groups: Optional[List[str]] = Field(None, description="Replaces the user's document access groups")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    role: str
    username: str
    expires_in: int
    must_change_password: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=1, max_length=128)


class TokenData(BaseModel):
    username: str
    role: str
    exp: Optional[int] = None
    token_type: str = "access"
    token_version: int = 0
