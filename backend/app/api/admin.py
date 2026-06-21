"""Phase 7 admin router — user management + page grants (brief §7.12).

All mutations require super_admin; read-only listing is allowed for admin.
Passwords are hashed on the way in and never returned. Page grants are stored
as PageGrant rows and replaced wholesale by the PUT endpoint.

This module owns no schema; it reuses the User/PageGrant/DashboardPage models.
A human wires this router into app/api/router.py separately.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin, require_super_admin
from app.auth.security import hash_password
from app.db.base import get_session
from app.db.models import ACCESS_LEVELS, DashboardPage, PageGrant, User

router = APIRouter(prefix="/admin", tags=["admin"])


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


class UserCreate(BaseModel):
    username: str
    password: str
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    address: str | None = None
    position: str | None = None
    access_level: str = "normal"
    is_active: bool = True


class UserUpdate(BaseModel):
    # Optional password reset; only applied when provided.
    password: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    address: str | None = None
    position: str | None = None
    access_level: str | None = None
    is_active: bool | None = None


class PageGrantUpdate(BaseModel):
    page_ids: list[int]


# ── helpers ─────────────────────────────────────────────────────────────
def _validate_level(level: str | None) -> None:
    if level is not None and level not in ACCESS_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"access_level must be one of {ACCESS_LEVELS}",
        )


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    return user


# ── user CRUD ───────────────────────────────────────────────────────────
@router.get("/users", response_model=list[UserOut])
async def list_users(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    stmt = select(User).order_by(User.id)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _admin: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
) -> User:
    _validate_level(body.access_level)
    existing = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        address=body.address,
        position=body.position,
        access_level=body.access_level,
        is_active=body.is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    _admin: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
) -> User:
    _validate_level(body.access_level)
    user = await _get_user_or_404(session, user_id)
    data = body.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password:
        user.password_hash = hash_password(password)
    for field, value in data.items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    _admin: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    user = await _get_user_or_404(session, user_id)
    await session.delete(user)
    await session.commit()


# ── page grants ─────────────────────────────────────────────────────────
@router.get("/users/{user_id}/pages", response_model=list[int])
async def get_user_pages(
    user_id: int,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[int]:
    await _get_user_or_404(session, user_id)
    stmt = select(PageGrant.page_id).where(PageGrant.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


@router.put("/users/{user_id}/pages", response_model=list[int])
async def set_user_pages(
    user_id: int,
    body: PageGrantUpdate,
    _admin: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
) -> list[int]:
    await _get_user_or_404(session, user_id)
    page_ids = sorted(set(body.page_ids))

    # Validate that all referenced pages exist before replacing grants.
    if page_ids:
        found = (
            (await session.execute(select(DashboardPage.id).where(DashboardPage.id.in_(page_ids))))
            .scalars()
            .all()
        )
        missing = set(page_ids) - set(found)
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"unknown page ids: {sorted(missing)}",
            )

    # Replace the full set of grants for this user.
    existing = (
        (await session.execute(select(PageGrant).where(PageGrant.user_id == user_id)))
        .scalars()
        .all()
    )
    for grant in existing:
        await session.delete(grant)
    for pid in page_ids:
        session.add(PageGrant(user_id=user_id, page_id=pid))
    await session.commit()
    return page_ids
