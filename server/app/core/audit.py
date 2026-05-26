"""
Вспомогательная функция записи в журнал действий (AuditLog).
Используется в users.py, database.py, pdf.py.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog, User


async def write_audit(
    db: AsyncSession,
    user: Optional[User],
    action: str,
    resource: str = None,
    details: str = None,
    ip: str = None,
    status: str = "success",
) -> None:
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        role=user.role.name.value if user else None,
        action=action,
        resource=resource,
        details=details,
        ip_address=ip,
        status=status,
    )
    db.add(log)
    await db.commit()
