"""
Начальное заполнение БД: роли и суперадмин.
Вызывается при каждом старте контейнера — идемпотентен.
"""
from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.core.config import settings
from app.models.models import Role, RoleName, User

logger = logging.getLogger(__name__)

# Роли с читаемыми названиями и описаниями
ROLES = [
    {
        "name":         RoleName.superadmin,
        "display_name": "Суперадминистратор",
        "description":  "Полные права: управление пользователями, БД, аналитика.",
    },
    {
        "name":         RoleName.administrator,
        "display_name": "Администратор",
        "description":  "Обновление базы товаров и констант брендов.",
    },
    {
        "name":         RoleName.manager,
        "display_name": "Менеджер",
        "description":  "Обработка PDF → коммерческое предложение.",
    },
    {
        "name":         RoleName.director,
        "display_name": "Директор",
        "description":  "Аналитика + обработка PDF → коммерческое предложение.",
    },
]


async def seed_roles(db: AsyncSession) -> dict[RoleName, Role]:
    """Создаёт роли если их нет. Возвращает словарь RoleName → Role."""
    role_map: dict[RoleName, Role] = {}
    for data in ROLES:
        q = await db.execute(select(Role).where(Role.name == data["name"]))
        role = q.scalar_one_or_none()
        if role is None:
            role = Role(**data)
            db.add(role)
            logger.info(f"[seed] Создана роль: {data['name'].value}")
        role_map[data["name"]] = role
    await db.commit()
    # перечитываем чтобы получить id после commit
    for data in ROLES:
        q = await db.execute(select(Role).where(Role.name == data["name"]))
        role_map[data["name"]] = q.scalar_one()
    return role_map


async def seed_superadmin(db: AsyncSession, role_map: dict[RoleName, Role]) -> None:
    """Создаёт суперадмина если в системе ещё нет пользователей."""
    q = await db.execute(select(User))
    if q.scalars().first() is not None:
        return  # пользователи уже есть — не трогаем

    superadmin_role = role_map[RoleName.superadmin]
    user = User(
        username=settings.SUPERADMIN_USERNAME,
        full_name="Суперадминистратор",
        password_hash=hash_password(settings.SUPERADMIN_PASSWORD),
        role_id=superadmin_role.id,
    )
    db.add(user)
    await db.commit()
    logger.info(
        f"[seed] Создан суперадмин '{settings.SUPERADMIN_USERNAME}'. "
        f"Смените пароль при первом входе!"
    )


async def run_seed() -> None:
    """Точка входа — вызывается из docker startup command."""
    async with AsyncSessionLocal() as db:
        role_map = await seed_roles(db)
        await seed_superadmin(db, role_map)
    logger.info("[seed] Готово.")
