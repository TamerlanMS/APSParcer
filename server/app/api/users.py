"""
API авторизации и управления пользователями.

POST  /api/v1/auth/login          — логин, возвращает JWT
POST  /api/v1/auth/logout         — отзыв текущей сессии
GET   /api/v1/auth/me             — текущий пользователь

GET   /api/v1/users/              — список пользователей (superadmin)
POST  /api/v1/users/              — создание пользователя (superadmin)
GET   /api/v1/users/{id}          — пользователь по ID (superadmin)
PATCH /api/v1/users/{id}          — обновление (superadmin)
DELETE /api/v1/users/{id}         — деактивация (superadmin)
GET   /api/v1/users/roles         — список ролей
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token,
    get_current_user, require_superadmin,
    verify_api_key,
)
from app.core.audit import write_audit
from app.models.models import User, Role, UserSession, RoleName

router = APIRouter(prefix="/api/v1", tags=["auth"])


# ── Схемы ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user_id: int
    username: str
    full_name: str
    role: str
    segment: str = "ss"

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    role: str
    role_display: str
    segment: str = "ss"
    is_active: bool
    created_at: Optional[datetime]
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    username: str
    full_name: str
    password: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: RoleName
    segment: str = "ss"

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль должен содержать не менее 6 символов")
        return v

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[RoleName] = None
    segment: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None

class RoleOut(BaseModel):
    name: str
    display_name: str
    description: Optional[str]


# ── Хелперы ───────────────────────────────────────────────────────────────────

def _user_to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role.name.value,
        role_display=user.role.display_name,
        segment=user.segment or "ss",
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# ── Авторизация ───────────────────────────────────────────────────────────────

class UserListItem(BaseModel):
    username:  str
    full_name: str


@router.get("/auth/users-list", response_model=List[UserListItem])
async def list_users_for_login(
    _key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Публичный (только API-ключ) список активных пользователей
    для выпадающего меню на экране входа.
    Не возвращает пароли, роли, email — только username + full_name.
    """
    q = await db.execute(
        select(User.username, User.full_name)
        .where(User.is_active == True)
        .order_by(User.full_name)
    )
    rows = q.all()
    return [UserListItem(username=r.username, full_name=r.full_name) for r in rows]


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else None

    q = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.username == body.username, User.is_active == True)
    )
    user = q.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        # Пишем неудачную попытку без user_id
        await write_audit(db, None, "login_failed",
                           resource=body.username, ip=ip, status="error")
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")

    token, jti, expires_at = create_access_token(
        user.id, user.username, user.role.name.value
    )

    # Сохраняем сессию
    session = UserSession(
        user_id=user.id,
        token_jti=jti,
        expires_at=expires_at,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", "")[:300],
    )
    db.add(session)

    # Обновляем last_login
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    await write_audit(db, user, "login", ip=ip)

    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role.name.value,
        segment=user.segment or "ss",
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отзывает текущую сессию (инвалидирует токен)."""
    from app.core.security import decode_token, bearer_scheme
    from fastapi.security import HTTPAuthorizationCredentials

    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if token:
        payload = decode_token(token)
        jti = payload.get("jti")
        q = await db.execute(
            select(UserSession).where(UserSession.token_jti == jti)
        )
        session = q.scalar_one_or_none()
        if session:
            session.is_active = False
            await db.commit()

    await write_audit(db, current_user, "logout",
                       ip=request.client.host if request.client else None)


@router.get("/auth/me", response_model=UserOut)
async def me(current_user=Depends(get_current_user)):
    return _user_to_out(current_user)


# ── Управление пользователями (только superadmin) ─────────────────────────────

@router.get("/users/roles", response_model=List[RoleOut])
async def list_roles(
    _=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Role).order_by(Role.id))
    return [
        RoleOut(name=r.name.value, display_name=r.display_name, description=r.description)
        for r in q.scalars().all()
    ]


@router.get("/users/", response_model=List[UserOut])
async def list_users(
    _=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(
        select(User).options(selectinload(User.role)).order_by(User.id)
    )
    return [_user_to_out(u) for u in q.scalars().all()]


@router.post("/users/", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    # Проверяем уникальность логина
    existing = await db.execute(
        select(User).where(User.username == body.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, detail=f"Пользователь '{body.username}' уже существует.")

    # Находим роль
    role_q = await db.execute(select(Role).where(Role.name == body.role))
    role = role_q.scalar_one_or_none()
    if not role:
        raise HTTPException(400, detail="Роль не найдена.")

    user = User(
        username=body.username,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role_id=role.id,
        segment=body.segment or "ss",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user, ["role"])
    await db.commit()

    await write_audit(db, current_user, "create_user",
                       resource=body.username,
                       ip=request.client.host if request.client else None)
    return _user_to_out(user)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    _=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id)
    )
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail="Пользователь не найден.")
    return _user_to_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id)
    )
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail="Пользователь не найден.")

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        user.email = body.email
    if body.phone is not None:
        user.phone = body.phone
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        if len(body.password) < 6:
            raise HTTPException(400, detail="Пароль должен содержать не менее 6 символов.")
        user.password_hash = hash_password(body.password)
    if body.segment is not None:
        user.segment = body.segment
    if body.role is not None:
        role_q = await db.execute(select(Role).where(Role.name == body.role))
        role = role_q.scalar_one_or_none()
        if not role:
            raise HTTPException(400, detail="Роль не найдена.")
        user.role_id = role.id
        await db.flush()
        await db.refresh(user, ["role"])

    await db.commit()
    await db.refresh(user)

    await write_audit(db, current_user, "update_user",
                       resource=user.username,
                       ip=request.client.host if request.client else None)
    return _user_to_out(user)


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user(
    user_id: int,
    request: Request,
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Деактивирует пользователя (не удаляет из БД)."""
    if user_id == current_user.id:
        raise HTTPException(400, detail="Нельзя деактивировать самого себя.")

    q = await db.execute(select(User).where(User.id == user_id))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail="Пользователь не найден.")

    user.is_active = False
    # Инвалидируем все активные сессии
    sessions_q = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id, UserSession.is_active == True
        )
    )
    for s in sessions_q.scalars().all():
        s.is_active = False

    await db.commit()
    await write_audit(db, current_user, "deactivate_user",
                       resource=user.username,
                       ip=request.client.host if request.client else None)
