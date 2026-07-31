"""
Фаза 4 — Аналитика.

GET  /api/v1/analytics/summary?period=30   — сводка по системе
GET  /api/v1/analytics/kpi?period=30       — KPI по менеджерам
GET  /api/v1/analytics/activity?period=30  — тепловая карта активности

Доступ: superadmin, administrator, director.
period = количество последних дней (7 / 30 / 90).

Статистика суперадминов и администраторов НЕ учитывается —
аналитика отражает только работу менеджеров и директоров.

Все временные метки переводятся в UTC+5 (Astana/Almaty).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
import json
from typing import Optional

from app.models.models import AuditLog, PdfUploadLog, User, Role, ManagerCorrection, Product, PriceHistory

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

require_analytics = require_roles("superadmin", "administrator", "director")

_EXCLUDED_ROLES = ("superadmin", "administrator")

# Сдвиг для перевода UTC → UTC+5 (Astana/Almaty)
_TZ5H = literal_column("INTERVAL '5 hours'")
_TZ5_DELTA = timedelta(hours=5)


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
        # date_trunc по локальному времени UTC+5
        _ts5 = PdfUploadLog.uploaded_at + _TZ5H
        q_daily = await db.execute(
            select(
                func.date_trunc("day", _ts5).label("day"),
                func.count(PdfUploadLog.id).label("kp_count"),
                func.coalesce(func.sum(PdfUploadLog.items_count), 0).label("items"),
            )
            .where(PdfUploadLog.uploaded_at >= since)
            .where(excl)
            .group_by(func.date_trunc("day", _ts5))
            .order_by(func.date_trunc("day", _ts5))
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
        # Переводим last_activity в UTC+5 для отображения
        last_act_local = (last_act + _TZ5_DELTA) if last_act else None
        result.append({
            "user_id":       r.user_id,
            "username":      r.username or "—",
            "full_name":     r.username or "—",
            "total_kp":      total_kp_r,
            "total_items":   total_items_r,
            "avg_items":     round(total_items_r / total_kp_r, 1) if total_kp_r else 0.0,
            "last_activity": last_act_local.strftime("%d.%m.%Y %H:%M") if last_act_local else "—",
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
        # Сдвигаем на UTC+5 перед извлечением часа и дня недели
        _ts5 = PdfUploadLog.uploaded_at + _TZ5H
        q = await db.execute(
            select(
                func.extract("dow",  _ts5).label("dow"),
                func.extract("hour", _ts5).label("hour"),
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


@router.get("/brands")
async def get_brand_analytics(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """Топ брендов по числу ручных исправлений менеджеров.
    Показывает, какие бренды чаще всего требуют вмешательства."""
    since = _since(period)

    # Топ-20 брендов по числу исправлений (через выбранный товар)
    q_brands = await db.execute(
        select(
            Product.brand,
            func.count(ManagerCorrection.id).label("corrections"),
            func.count(func.distinct(ManagerCorrection.user_id)).label("unique_users"),
        )
        .join(Product, ManagerCorrection.selected_product_id == Product.id)
        .where(ManagerCorrection.created_at >= since)
        .where(Product.brand.isnot(None))
        .group_by(Product.brand)
        .order_by(func.count(ManagerCorrection.id).desc())
        .limit(20)
    )
    top_brands = [
        {
            "brand":        r.brand,
            "corrections":  int(r.corrections),
            "unique_users": int(r.unique_users),
        }
        for r in q_brands.all()
    ]

    total = sum(b["corrections"] for b in top_brands)
    for b in top_brands:
        b["pct"] = round(b["corrections"] / total * 100, 1) if total else 0.0

    # Разбивка по исходному статусу всех исправлений за период
    q_status = await db.execute(
        select(
            ManagerCorrection.original_status,
            func.count(ManagerCorrection.id).label("cnt"),
        )
        .where(ManagerCorrection.created_at >= since)
        .group_by(ManagerCorrection.original_status)
    )
    by_status = {
        (r.original_status or "unknown"): int(r.cnt)
        for r in q_status.all()
    }

    return {
        "period_days":        period,
        "top_brands":         top_brands,
        "total_corrections":  total,
        "by_original_status": by_status,
    }


@router.get("/ai-efficiency")
async def get_ai_efficiency(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """Отчёт по эффективности ИИ-подбора.
    Показывает частоту ручных исправлений, разбивку по исходным статусам
    и прогресс индексации исправлений в Pinecone."""
    since = _since(period)
    excl  = _excl_admins_filter()

    # Всего позиций в КП за период (исключая администраторов)
    q_items = await db.execute(
        select(func.coalesce(func.sum(PdfUploadLog.items_count), 0))
        .where(PdfUploadLog.uploaded_at >= since)
        .where(excl)
    )
    total_items = int(q_items.scalar() or 0)

    # Всего ручных исправлений за период
    q_total = await db.execute(
        select(func.count(ManagerCorrection.id))
        .where(ManagerCorrection.created_at >= since)
    )
    total_corrections = int(q_total.scalar() or 0)

    # Разбивка по исходному статусу (что было до вмешательства менеджера)
    q_status = await db.execute(
        select(
            ManagerCorrection.original_status,
            func.count(ManagerCorrection.id).label("cnt"),
        )
        .where(ManagerCorrection.created_at >= since)
        .group_by(ManagerCorrection.original_status)
        .order_by(func.count(ManagerCorrection.id).desc())
    )
    by_status = [
        {"status": r.original_status or "unknown", "count": int(r.cnt)}
        for r in q_status.all()
    ]

    # Проиндексировано в Pinecone
    q_indexed = await db.execute(
        select(func.count(ManagerCorrection.id))
        .where(ManagerCorrection.created_at >= since)
        .where(ManagerCorrection.pinecone_indexed.is_(True))
    )
    indexed_count = int(q_indexed.scalar() or 0)

    # Топ менеджеров по числу исправлений (кто больше всего обучает ИИ)
    q_mgr = await db.execute(
        select(
            ManagerCorrection.username,
            func.count(ManagerCorrection.id).label("corrections"),
        )
        .where(ManagerCorrection.created_at >= since)
        .where(ManagerCorrection.username.isnot(None))
        .group_by(ManagerCorrection.username)
        .order_by(func.count(ManagerCorrection.id).desc())
        .limit(10)
    )
    by_manager = [
        {"username": r.username, "corrections": int(r.corrections)}
        for r in q_mgr.all()
    ]

    correction_rate = round(total_corrections / total_items * 100, 1) if total_items else 0.0
    indexing_rate   = round(indexed_count / total_corrections * 100, 1) if total_corrections else 0.0

    return {
        "period_days":       period,
        "total_items":       total_items,
        "total_corrections": total_corrections,
        "correction_rate":   correction_rate,
        "indexed_count":     indexed_count,
        "indexing_rate":     indexing_rate,
        "by_status":         by_status,
        "by_manager":        by_manager,
    }


@router.get("/price-history")
async def get_price_history(
    article: str = Query(..., min_length=1),
    segment: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """История цен по артикулу.
    Возвращает снимки старых цен (из price_history) + текущую цену (из products).
    """
    # ── Архивные снимки (сохранены при каждом импорте с изменением цены) ──────
    hist_q = select(
        PriceHistory.article, PriceHistory.brand, PriceHistory.name,
        PriceHistory.segment, PriceHistory.kaznisa, PriceHistory.rrts,
        PriceHistory.mrc, PriceHistory.opt, PriceHistory.recorded_at,
    ).where(PriceHistory.article == article)
    if segment:
        hist_q = hist_q.where(PriceHistory.segment == segment)
    hist_q = hist_q.order_by(PriceHistory.recorded_at)
    hist_rows = (await db.execute(hist_q)).all()

    # ── Текущая цена ──────────────────────────────────────────────────────────
    curr_q = select(
        Product.article, Product.brand, Product.name,
        Product.segment, Product.kaznisa, Product.rrts,
        Product.mrc, Product.opt, Product.created_at,
    ).where(Product.article == article, Product.is_active == True)
    if segment:
        curr_q = curr_q.where(Product.segment == segment)
    curr_rows = (await db.execute(curr_q)).all()

    def _fmt(r, ts_col: str, is_current: bool) -> dict:
        ts = getattr(r, ts_col, None)
        ts_local = (ts + _TZ5_DELTA) if ts else None
        return {
            "date":       ts_local.strftime("%d.%m.%Y %H:%M") if ts_local else "—",
            "brand":      r.brand or "—",
            "name":       r.name  or "—",
            "segment":    r.segment or "—",
            "kaznisa":    float(r.kaznisa or 0),
            "rrts":       float(r.rrts    or 0),
            "mrc":        float(r.mrc     or 0),
            "opt":        float(r.opt     or 0),
            "is_current": is_current,
        }

    history = [_fmt(r, "recorded_at", False) for r in hist_rows]
    current = [_fmt(r, "created_at",  True)  for r in curr_rows]
    records = history + current

    return {
        "article": article,
        "segment": segment,
        "found":   len(records) > 0,
        "records": records,
    }


@router.get("/anomalies")
async def get_anomalies(
    period: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_analytics),
):
    """Аномалии цен — изменения > 15% при импорте за период."""
    since = _since(period)

    q = await db.execute(
        select(AuditLog.resource, AuditLog.details, AuditLog.created_at)
        .where(AuditLog.action == "price_anomaly")
        .where(AuditLog.created_at >= since)
        .order_by(AuditLog.created_at.desc())
        .limit(500)
    )

    anomalies = []
    for r in q.all():
        try:
            det = json.loads(r.details or "{}")
        except Exception:
            det = {}
        ts = r.created_at
        ts_local = (ts + _TZ5_DELTA) if ts else None
        parts = (r.resource or "/").split("/", 1)
        pct = det.get("pct_change", 0)
        anomalies.append({
            "segment":    parts[0] if parts else "—",
            "article":    parts[1] if len(parts) > 1 else "—",
            "brand":      det.get("brand", "—"),
            "name":       det.get("name",  "—"),
            "field":      det.get("field", "—"),
            "old_price":  det.get("old_price",  0),
            "new_price":  det.get("new_price",  0),
            "pct_change": pct,
            "direction":  "▲" if pct > 0 else "▼",
            "date":       ts_local.strftime("%d.%m.%Y %H:%M") if ts_local else "—",
        })

    return {
        "period_days": period,
        "count":       len(anomalies),
        "anomalies":   anomalies,
    }
