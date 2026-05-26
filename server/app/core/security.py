"""
Безопасность: API-ключ (старый клиент), JWT (новый), RBAC-зависимости.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# ── Схемы безопасности ────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme  = HTTPBearer(auto_error=False)


# ── Хеширование паролей ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, username: str, role: str) -> tuple:
    """Создаёт JWT. Возвращает (token, jti, expires_at)."""
    jti        = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload    = {
        "sub":      str(user_id),
        "username": username,
        "role":     role,
        "jti":      jti,
        "exp":      expires_at,
        "iat":      datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    """Декодирует JWT. Выбрасывает HTTPException при невалидном токене."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен истёк. Войдите заново.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен.")


# ── Зависимости FastAPI ───────────────────────────────────────────────────────

async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Обратная совместимость — старый десктоп-клиент."""
    if not api_key or api_key not in settings.API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недействительный API ключ. Доступ запрещён.",
        )
    return api_key


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает текущего пользователя по JWT Bearer токену."""
    from app.models.models import User, UserSession  # локальный импорт → нет цикла

    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")

    payload = decode_token(credentials.credentials)
    jti     = payload.get("jti")
    user_id = int(payload.get("sub", 0))

    # Проверяем что сессия не отозвана
    session_q = await db.execute(
        select(UserSession).where(
            UserSession.token_jti == jti,
            UserSession.is_active == True,
        )
    )
    if not session_q.scalar_one_or_none():
        raise HTTPException(status_code=401, detail="Сессия завершена. Войдите заново.")

    from sqlalchemy.orm import selectinload
    user_q = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id, User.is_active == True)
    )
    user = user_q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден или деактивирован.")
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает пользователя или None (не выбрасывает 401)."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def verify_any_auth(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    Принимает X-API-Key (старый клиент) ИЛИ Bearer JWT (новый клиент).
    Возвращает строку-идентификатор метода: 'api_key' | 'jwt'.
    Выбрасывает 401 если ни один метод не прошёл.
    """
    # Приоритет 1: API-ключ
    if api_key and api_key in settings.API_KEYS:
        return "api_key"

    # Приоритет 2: JWT Bearer
    if credentials:
        try:
            await get_current_user(credentials, db)
            return "jwt"
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Токен недействителен или истёк. Войдите заново.",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация: передайте X-API-Key или Bearer токен.",
    )


def require_roles(*roles: str):
    """
    Фабрика зависимостей для проверки роли.
    Пример: Depends(require_roles("superadmin", "administrator"))
    """
    async def _check(user=Depends(get_current_user)):
        if user.role.name.value not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Доступ запрещён. Требуется одна из ролей: {', '.join(roles)}",
            )
        return user
    return _check


# ── Готовые комбинации ────────────────────────────────────────────────────────
require_superadmin  = require_roles("superadmin")
require_admin_up    = require_roles("superadmin", "administrator")
require_manager_up  = require_roles("superadmin", "administrator", "manager", "director")
require_director_up = require_roles("superadmin", "director")
