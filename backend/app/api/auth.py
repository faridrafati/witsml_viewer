"""Phase 7 authentication router (brief §7.12).

Exposes the OAuth2 password-flow login that mints a JWT and a `/me` echo of
the authenticated principal. Tokens carry the username as `sub` and the
access level as `lvl` so downstream RBAC gates can read the role without an
extra DB hit (they still re-load the user for is_active/freshness).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import authenticate_user, get_current_user
from app.auth.security import create_access_token
from app.db.base import get_session
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ── schemas ─────────────────────────────────────────────────────────────
class UserOut(BaseModel):
    """Public view of a user — never includes password_hash."""

    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    address: str | None = None
    position: str | None = None
    access_level: str
    is_active: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── routes ──────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    """OAuth2 password grant — exchange username/password for a JWT."""
    user = await authenticate_user(session, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        subject=user.username,
        extra={"lvl": user.access_level},
    )
    return TokenOut(
        access_token=token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def read_me(user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user (no password hash)."""
    return user
