"""Sign-in: local users and their API tokens (``chatppt/auth/store.py`` reads and writes these).

Times are Unix seconds, so SQLite, Postgres and MySQL all round-trip them the same way.
"""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class UserModel(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    # Lower-cased; what people type to sign in.
    username: str = Field(index=True, unique=True, max_length=128)
    # pbkdf2_sha256$<iterations>$<salt>$<digest>; None for SSO-only users.
    password_hash: Optional[str] = Field(default=None, max_length=256)
    is_admin: bool = Field(default=False)
    is_active: bool = Field(default=True)
    # Bumped to sign the user out everywhere (password change, "sign out everywhere", disable).
    session_version: int = Field(default=1)
    # local | oidc | proxy: how the user was created.
    source: str = Field(default="local", max_length=16)
    created_at: int = Field(default=0)
    last_login_at: Optional[int] = Field(default=None)


class ApiTokenModel(SQLModel, table=True):
    __tablename__ = "api_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
    name: str = Field(max_length=128)
    # The first characters of the token, shown in lists so people can tell tokens apart.
    prefix: str = Field(max_length=16)
    # sha256 hex of the full token; the token itself is shown once and never stored.
    token_hash: str = Field(index=True, unique=True, max_length=64)
    created_at: int = Field(default=0)
    last_used_at: Optional[int] = Field(default=None)
