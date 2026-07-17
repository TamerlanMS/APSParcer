"""
Фаза 4 — Аналитика.

GET  /api/v1/analytics/summary?period=30   — сводка по системе
GET  /api/v1/analytics/kpi?period=30       — KPI по менеджерам
GET  /api/v1/analytics/activity?period=30  — тепловая карта активности

Доступ: superadmin, administrator, director.
period = количество последних дней (7 / 30 / 90).

Статистика суперадминов и администраторов НЕ учитывается —
аналитика отражает только работу менеджеров и директоров.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
from app.models.models import AuditLog, PdfUploadLog, User, Role

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

require_analytics = require_roles("superadmin", "administrator", "director")

_EXCLUDED_ROLES = ("superadmin", "administrator")


def _since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _excl_admins_filter():
    """Exclude superadmin/administrator uploads from PdfUploadLog queries."""
    admin_ids = (
        select(User.id)
        .join(Role, User.role_id == Role.id)
        .where(Role.name.in_(_EXCLUDED_ROLES))
        .scalar_subquery()
    )
    return or_(
        PdfUploadLog.user_id.is_(None),
        PdfUploadLog.user_id.not_in(admin_ids),
    )


@router.get("/summary")
async def get_summary(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    since = _since(period)
    excl  = _excl_admins_filter()

    q_agg = await db.execute(
        select(
            func.count(PdfUploadLog.id).label("total_kp"),
            func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("total_items"),
        )
        .where(PdfUploadLog.uploaded_at >= since)
        .where(excl)
    )
    agg = q_agg.one()
    total_kp    = int(agg.total_kp)
    total_items = int(agg.total_items)
    avg_items   = round(total_items / total_kp, 1) if total_kp else 0.0

    q_mgr = await db.execute(
        select(PdfUploadLog.user_id)
        .where(PdfUploadLog.uploaded_at >= since)
        .where(PdfUploadLog.user_id.isnot(None))
        .where(excl)
        .group_by(PdfUploadLog.user_id)
    )
    active_managers = len(q_mgr.all())

    q_err = await db.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.created_at >= since)
        .where(AuditLog.status == "error")
        .where(
            or_(
                AuditLog.role.is_(None),
                AuditLog.role.not_in(_EXCLUDED_ROLES),
            )
        )
    )
    total_errors = int(q_err.scalar() or 0)

    try:
        q_daily = await db.execute(
            select(
                func.date_trunc("day", PdfUploadLog.uploaded_at).label("day"),
                func.count(PdfUploadLog.id).label("kp_count"),
                func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("items"),
            )
            .where(PdfUploadLog.uploaded_at >= since)
            .where(excl)
            .group_by(func.date_trunc("day", PdfUploadLog.uploaded_at))
            .order_by(func.date_trunc("day", PdfUploadLog.uploaded_at))
        )
        daily = [
            {
                "day":      r.day.strftime("%d.%m") if r.day else "",
                "kp_count": int(r.kp_count),
                "items":    int(r.items),
            }
            for r in q_daily.all()
        ]
    except Exception:
        daily = []

    return {
        "period_days":      period,
        "total_kp":         total_kp,
        "total_items":      total_items,
        "active_managers":  active_managers,
        "avg_items_per_kp": avg_items,
        "total_errors":     total_errors,
        "daily":            daily,
    }


@router.get("/kpi")
async def get_kpi(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """KPI по менеджерам за период. Суперадмины и администраторы исключены."""
    since = _since(period)
    excl  = _excl_admins_filter()

    q = await db.execute(
        select(
            PdfUploadLog.user_id,
            PdfUploadLog.username,
            func.count(PdfUploadLog.id).label("total_kp"),
            func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("total_items"),
            func.max(PdfUploadLog.uploaded_at).label("last_activity"),
        )
        .where(PdfUploadLog.uploaded_at >= since)
        .where(excl)
        .group_by(PdfUploadLog.user_id, PdfUploadLog.username)
        .order_by(func.count(PdfUploadLog.id).desc())
    )

    result = []
    for r in q.all():
        last_act      = r.last_activity
        total_kp_r    = int(r.total_kp)
        total_items_r = int(r.total_items)
        result.append({
            "user_id":       r.user_id,
            "username":      r.username or "—",
            "full_name":     r.username or "—",
            "total_kp":      total_kp_r,
            "total_items":   total_items_r,
            "avg_items":     round(total_items_r / total_kp_r, 1) if total_kp_r else 0.0,
            "last_activity": last_act.strftime("%d.%m.%Y %H:%M") if last_act else "—",
        })

    return {"period_days": period, "managers": result}


@router.get("/activity")
async def get_activity(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """Тепловая карта активности. Суперадмины и администраторы исключены."""
    since = _since(period)
    excl  = _excl_admins_filter()
    try:
        q = await db.execute(
            select(
                func.extract("dow",  PdfUploadLog.uploaded_at).label("dow"),
                func.extract("hour", PdfUploadLog.uploaded_at).label("hour"),
                func.count(PdfUploadLog.id).label("cnt"),
            )
            .where(PdfUploadLog.uploaded_at >= since)
            .where(excl)
            .group_by("dow", "hour")
            .order_by("dow", "hour")
        )
        activity = [
            {"dow": int(r.dow), "hour": int(r.hour), "count": int(r.cnt)}
            for r in q.all()
        ]
    except Exception:
        activity = []

    return {"period_days": period, "activity": activity}
