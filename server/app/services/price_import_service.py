"""
PriceImportService — оркестратор импорта прайсов.
parse → diff → (подтверждение оператора) → apply
"""
from __future__ import annotations
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.models.models import (
    Product
)
from app.services.price_parser.registry    import ParserRegistry
from app.services.price_parser.diff_engine import build_diff, DiffReport

logger = logging.getLogger(__name__)
_registry = ParserRegistry()


# ─── Вспомогательные ──────────────────────────────────────────────────────────

async def _get_or_create_supplier(db: AsyncSession, code: str, name: str) -> Supplier:
    result = await db.execute(select(Supplier).where(Supplier.code == code))
    sup = result.scalar_one_or_none()
    if sup is None:
        sup = Supplier(code=code, name=name)
        db.add(sup)
        await db.flush()
    return sup


async def _load_existing_products(db: AsyncSession) -> dict:
    """Загружает все активные продукты как dict {article: {fields}}."""
    result = await db.execute(
        select(Product).where(Product.is_active == True)
    )
    prods = result.scalars().all()
    return {
        p.article: {
            "id":          p.id,
            "name":        p.name,
            "unit":        p.unit,
            "brand":       p.brand,
            "multiplicity": p.multiplicity,
            "rrts":        p.rrts,
            "opt":         p.opt,
            "partner":     p.partner,
            "kaznisa":     p.kaznisa,
        }
        for p in prods if p.article
    }


# ─── Публичные функции ─────────────────────────────────────────────────────────

async def parse_and_diff(
    db: AsyncSession,
    file_path: str,
    original_filename: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    force_remap: bool = False,
) -> dict:
    """
    Шаг 1: парсим прайс через Claude API (с кэшем),
    сравниваем с БД, сохраняем SupplierImportLog в статусе 'pending'.
    Возвращает словарь с job_id и summary диффа.
    """
    supplier_code, supplier_name, items = await _registry.parse_file(
        file_path, db=db, force_remap=force_remap
    )

    if supplier_code is None:
        return {"error": "supplier_not_detected",
                "detail": "Поставщик не распознан. Проверьте ANTHROPIC_API_KEY."}

    existing = await _load_existing_products(db)
    report   = build_diff(
        supplier_code = supplier_code,
        filename      = original_filename,
        incoming      = items,
        existing      = existing,
    )

    supplier = await _get_or_create_supplier(db, supplier_code, supplier_name or supplier_code)

    log = SupplierImportLog(
        supplier_id   = supplier.id,
        supplier_code = supplier_code,
        filename      = original_filename,
        rows_total    = report.rows_total,
        rows_new      = report.rows_new,
        rows_updated  = report.rows_updated,
        rows_deleted  = report.rows_deleted,
        rows_skipped  = report.rows_skipped,
        status        = "pending",
        diff_json     = json.dumps(report.to_dict(), ensure_ascii=False, default=str),
        user_id       = user_id,
        username      = username,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    return {
        "job_id":        log.id,
        "supplier":      supplier_code,
        "supplier_name": supplier_name,
        **report.summary(),
        "preview": [
            {
                "article": r.article,
                "kind":    r.kind,
                "name":    r.name,
                "brand":   r.brand,
                "changes": r.changes,
            }
            for r in report.records[:20]
        ],
    }


async def get_diff(db: AsyncSession, job_id: int) -> dict:
    """Возвращает полный дифф по job_id."""
    result = await db.execute(
        select(SupplierImportLog).where(SupplierImportLog.id == job_id)
    )
    log = result.scalar_one_or_none()
    if log is None:
        return {"error": "not_found"}

    diff = json.loads(log.diff_json) if log.diff_json else {}
    return {
        "job_id":      log.id,
        "status":      log.status,
        "supplier":    log.supplier_code,
        "filename":    log.filename,
        "created_at":  log.created_at,
        **diff,
    }


async def confirm_import(
    db: AsyncSession,
    job_id: int,
    user_id: Optional[int] = None,
) -> dict:
    """
    Шаг 2: применяем изменения из диффа к таблице products,
    пишем историю цен, обновляем статус лога.
    """
    result = await db.execute(
        select(SupplierImportLog).where(SupplierImportLog.id == job_id)
    )
    log = result.scalar_one_or_none()
    if log is None:
        return {"error": "not_found"}
    if log.status != "pending":
        return {"error": "already_processed", "status": log.status}

    diff_data = json.loads(log.diff_json) if log.diff_json else {"records": []}
    records   = diff_data.get("records", [])

    applied_new = 0
    applied_upd = 0
    history_rows = []

    for rec in records:
        article = rec["article"]
        kind    = rec["kind"]
        changes = rec.get("changes", {})

        if kind == "deleted":
            # Помечаем как неактивный
            res = await db.execute(select(Product).where(Product.article == article))
            prod = res.scalar_one_or_none()
            if prod:
                prod.is_active = False
            continue

        if kind == "new":
            # Создаём новую запись
            prod = Product(
                article  = article,
                name     = rec.get("name", ""),
                brand    = rec.get("brand") or None,
                is_active = True,
            )
            # Применяем цены
            for db_field, vals in changes.items():
                if hasattr(prod, db_field):
                    setattr(prod, db_field, vals["new"])
            db.add(prod)
            applied_new += 1

        elif kind == "updated":
            res = await db.execute(select(Product).where(Product.article == article))
            prod = res.scalar_one_or_none()
            if prod is None:
                continue
            for db_field, vals in changes.items():
                if hasattr(prod, db_field):
                    old_val = vals.get("old")
                    new_val = vals.get("new")
                    setattr(prod, db_field, new_val)
                    history_rows.append(PriceHistory(
                        supplier_id   = log.supplier_id,
                        supplier_code = log.supplier_code,
                        article       = article,
                        field         = db_field,
                        old_value     = old_val,
                        new_value     = new_val,
                        import_log_id = log.id,
                    ))
            applied_upd += 1

    db.add_all(history_rows)

    log.status       = "confirmed"
    log.confirmed_at = datetime.now(timezone.utc)
    log.rows_new     = applied_new
    log.rows_updated = applied_upd

    await db.commit()

    return {
        "job_id":        log.id,
        "status":        "confirmed",
        "rows_applied":  applied_new + applied_upd,
        "rows_new":      applied_new,
        "rows_updated":  applied_upd,
    }


async def get_price_history(db: AsyncSession, article: str, limit: int = 50) -> list:
    """История изменений цен для конкретного артикула."""
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.article == article)
        .order_by(PriceHistory.changed_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        {
            "supplier_code": r.supplier_code,
            "field":         r.field,
            "old_value":     r.old_value,
            "new_value":     r.new_value,
            "changed_at":    r.changed_at,
        }
        for r in rows
    ]


async def list_suppliers(db: AsyncSession) -> list:
    result = await db.execute(select(Supplier).where(Supplier.is_active == True))
    sups = result.scalars().all()
    return [
        {
            "id":   s.id,
            "code": s.code,
            "name": s.name,
        }
        for s in sups
    ]


async def list_import_logs(db: AsyncSession, limit: int = 50) -> list:
    result = await db.execute(
        select(SupplierImportLog)
        .order_by(SupplierImportLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id":           l.id,
            "supplier":     l.supplier_code,
            "filename":     l.filename,
            "status":       l.status,
            "rows_total":   l.rows_total,
            "rows_new":     l.rows_new,
            "rows_updated": l.rows_updated,
            "created_at":   l.created_at,
        }
        for l in logs
    ]
