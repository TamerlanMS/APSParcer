"""
Фаза 4 — Аналитика.

GET  /api/v1/analytics/summary?period=30   — сводка по системе
GET  /api/v1/analytics/kpi?period=30       — KPI по менеджерам

Доступ: superadmin, administrator, director.
period = количество последних дней (7 / 30 / 90).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
from app.models.models import AuditLog, PdfUploadLog

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# Аналитика доступна: суперадмин, администратор, директор
require_analytics = require_roles("superadmin", "administrator", "director")


def _since(days: int) -> datetime:
    """Наивный UTC datetime (asyncpg-совместимый)."""
    return datetime.utcnow() - timedelta(days=days)


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """
    Сводная статистика за период (days):
      total_kp, total_items, active_managers, avg_items_per_kp,
      total_errors, daily (список {day, kp_count, items}).
    """
    since = _since(period)

    # ── Агрегаты по pdf_upload_logs ───────────────────────────────────────────
    q_agg = await db.execute(
        select(
            func.count(PdfUploadLog.id).label("total_kp"),
            func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("total_items"),
        ).where(PdfUploadLog.uploaded_at >= since)
    )
    agg = q_agg.one()
    total_kp    = int(agg.total_kp)
    total_items = int(agg.total_items)
    avg_items   = round(total_items / total_kp, 1) if total_kp else 0.0

    # ── Уникальные менеджеры (отдельный запрос — без distinct внутри count) ───
    q_mgr = await db.execute(
        select(PdfUploadLog.user_id)
        .where(PdfUploadLog.uploaded_at >= since)
        .where(PdfUploadLog.user_id.isnot(None))
        .group_by(PdfUploadLog.user_id)
    )
    active_managers = len(q_mgr.all())

    # ── Ошибки из AuditLog ────────────────────────────────────────────────────
    q_err = await db.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.created_at >= since)
        .where(AuditLog.status == "error")
    )
    total_errors = int(q_err.scalar() or 0)

    # ── Активность по дням (PostgreSQL date_trunc) ────────────────────────────
    try:
        q_daily = await db.execute(
            select(
                func.date_trunc("day", PdfUploadLog.uploaded_at).label("day"),
                func.count(PdfUploadLog.id).label("kp_count"),
                func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("items"),
            )
            .where(PdfUploadLog.uploaded_at >= since)
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


# ── KPI по менеджерам ─────────────────────────────────────────────────────────

@router.get("/kpi")
async def get_kpi(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """
    KPI на каждого менеджера за период.
    Данные из pdf_upload_logs, сгруппированные по (user_id, username, full_name).
    """
    since = _since(period)

    # full_name может отсутствовать в старых БД — используем COALESCE через text()
    q = await db.execute(
        select(
            PdfUploadLog.user_id,
            PdfUploadLog.username,
            func.count(PdfUploadLog.id).label("total_kp"),
            func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("total_items"),
            func.max(PdfUploadLog.uploaded_at).label("last_activity"),
        )
        .where(PdfUploadLog.uploaded_at >= since)
        .group_by(PdfUploadLog.user_id, PdfUploadLog.username)
        .order_by(func.count(PdfUploadLog.id).desc())
    )
    rows = q.all()

    result = []
    for r in rows:
        last_act = r.last_activity
        total_kp_r    = int(r.total_kp)
        total_items_r = int(r.total_items)
        result.append({
            "user_id":       r.user_id,
            "username":      r.username or "—",
            "full_name":     r.username or "—",  # full_name берём из username (совместимость)
            "total_kp":      total_kp_r,
            "total_items":   total_items_r,
            "avg_items":     round(total_items_r / total_kp_r, 1) if total_kp_r else 0.0,
            "last_activity": last_act.strftime("%d.%m.%Y %H:%M") if last_act else "—",
        })

    return {
        "period_days": period,
        "managers":    result,
    }


# ── Активность по часам ───────────────────────────────────────────────────────

@router.get("/activity")
async def get_activity(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """Распределение активности по дням недели и часам (тепловая карта)."""
    since = _since(period)
    try:
        q = await db.execute(
            select(
                func.extract("dow",  PdfUploadLog.uploaded_at).label("dow"),
                func.extract("hour", PdfUploadLog.uploaded_at).label("hour"),
                func.count(PdfUploadLog.id).label("cnt"),
            )
            .where(PdfUploadLog.uploaded_at >= since)
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
