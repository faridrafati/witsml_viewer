"""Auth dependencies + RBAC enforcement (brief §7.12).

Builds on app.auth.security (hash/verify, JWT). Provides FastAPI dependencies
for the current user and role gates. Access levels (ascending):
    normal < admin < super_admin
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token, verify_password
from app.db.base import get_session
from app.db.models import User

# tokenUrl points at the login route mounted under /api/auth (Phase 7 router).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

_LEVEL_RANK = {"normal": 0, "admin": 1, "super_admin": 2}


async def authenticate_user(session: AsyncSession, username: str, password: str) -> User | None:
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_exc
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise cred_exc from exc
    username = payload.get("sub")
    if not username:
        raise cred_exc
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise cred_exc
    return user


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Like get_current_user but returns None instead of raising (mixed auth)."""
    if not token:
        return None
    try:
        return await get_current_user(token=token, session=session)
    except HTTPException:
        return None


def require_level(min_level: str):
    """Dependency factory gating a route on a minimum access level."""
    floor = _LEVEL_RANK.get(min_level, 0)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if _LEVEL_RANK.get(user.access_level, 0) < floor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires {min_level} access",
            )
        return user

    return _dep


require_admin = require_level("admin")
require_super_admin = require_level("super_admin")


def user_can_access_page(
    user: User, page_owner_id: int | None, granted_page_ids: set[int], page_id: int
) -> bool:
    """Admins see everything; others need ownership or an explicit grant."""
    if _LEVEL_RANK.get(user.access_level, 0) >= _LEVEL_RANK["admin"]:
        return True
    if page_owner_id is not None and page_owner_id == user.id:
        return True
    return page_id in granted_page_ids
