"""
POST /api/v1/analogs/search  — поиск аналога по артикулу через внешние провайдеры.

Алгоритм:
  1. Проверяем кэш product_analogs (срок годности 30 дней).
  2. Если кэш свеж — используем его.
  3. Иначе — вызываем провайдера, сохраняем результаты в кэш.
  4. Для каждого analog_article делаем lookup во внутренней БД products.
  5. Возвращаем список с флагом db_match и полными данными товара если найден.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Product, ProductAnalog
from app.services.analog_providers import PROVIDERS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analogs", tags=["analogs"])

CACHE_TTL_DAYS = 30


# ─── Request / Response schemas ───────────────────────────────────────────────

class AnalogSearchRequest(BaseModel):
    article: str
    provider: str                   # dkc | ekf | iek | chint | bonpet
    force_refresh: bool = False
    segment: str = "ss"             # ss / os / sil — фильтр внутренней БД


class AnalogItem(BaseModel):
    analog_article: str
    analog_name: Optional[str] = None
    source: str
    db_match: Optional[dict] = None   # Product fields if found in internal DB


class AnalogSearchResponse(BaseModel):
    analogs: list[AnalogItem]
    cached: bool
    provider_error: Optional[str] = None


# ─── Helper: lookup analog article in products table ─────────────────────────

async def _db_lookup(article: str, db: AsyncSession,
                     segment: Optional[str] = None) -> Optional[dict]:
    """Search products by article (case-insensitive, strips spaces/dashes).
    Filters by segment if provided."""
    clean = article.upper().replace(" ", "").replace("-", "")
    stmt = (
        select(Product)
        .where(
            func.upper(func.replace(func.replace(Product.article, " ", ""), "-", "")) == clean
        )
        .where(Product.is_active == True)  # noqa: E712
    )
    if segment:
        stmt = stmt.where(Product.segment == segment)
    stmt = stmt.limit(1)
    q = await db.execute(stmt)
    p = q.scalars().first()
    if not p:
        # Fallback: try without segment filter (аналог может быть из другого сегмента)
        if segment:
            q2 = await db.execute(
                select(Product)
                .where(
                    func.upper(
                        func.replace(func.replace(Product.article, " ", ""), "-", "")
                    ) == clean
                )
                .where(Product.is_active == True)  # noqa: E712
                .limit(1)
            )
            p = q2.scalars().first()
        if not p:
            return None
    return {
        "id":           p.id,
        "article":      p.article,
        "name":         p.name,
        "unit":         p.unit,
        "kaznisa":      p.kaznisa,
        "rrts":         p.rrts,
        "mrc":          p.mrc,
        "opt":          p.opt,
        "partner":      p.partner,
        "brand":        p.brand,
        "multiplicity": p.multiplicity,
        "segment":      p.segment,
    }


# ─── Main endpoint ────────────────────────────────────────────────────────────

@router.post("/search", response_model=AnalogSearchResponse)
async def search_analogs(
    body: AnalogSearchRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    article  = body.article.strip()
    provider = body.provider.lower().strip()
    segment  = body.segment or "ss"

    if provider not in PROVIDERS:
        return AnalogSearchResponse(
            analogs=[],
            cached=False,
            provider_error=f"Неизвестный провайдер: {provider}. "
                           f"Доступны: {', '.join(PROVIDERS)}",
        )

    # ── 1. Check cache ────────────────────────────────────────────────────────
    cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)
    cached = False

    if not body.force_refresh:
        q_cache = await db.execute(
            select(ProductAnalog)
            .where(ProductAnalog.article == article)
            .where(ProductAnalog.source  == provider)
            .where(ProductAnalog.fetched_at >= cutoff)
        )
        cached_rows = q_cache.scalars().all()

        if cached_rows:
            cached = True
            analogs: list[AnalogItem] = []
            for row in cached_rows:
                db_match = await _db_lookup(row.analog_article, db, segment)
                analogs.append(AnalogItem(
                    analog_article=row.analog_article,
                    analog_name=row.analog_name,
                    source=row.source,
                    db_match=db_match,
                ))
            return AnalogSearchResponse(analogs=analogs, cached=True)

    # ── 2. Call provider ──────────────────────────────────────────────────────
    _, search_fn = PROVIDERS[provider]
    try:
        raw_results, error = await search_fn(article)
    except Exception as e:
        log.error("Provider %s raised exception: %s", provider, e)
        raw_results, error = [], f"{provider}: внутренняя ошибка — {e}"

    # ── 3. Invalidate old cache entries for this article+provider ─────────────
    if raw_results:
        await db.execute(
            delete(ProductAnalog)
            .where(ProductAnalog.article == article)
            .where(ProductAnalog.source  == provider)
        )
        for r in raw_results:
            db.add(ProductAnalog(
                article=article,
                source=provider,
                analog_article=r.analog_article,
                analog_name=r.analog_name,
                expires_at=datetime.utcnow() + timedelta(days=CACHE_TTL_DAYS),
            ))
        await db.commit()

    # ── 4. Build response with DB lookups ─────────────────────────────────────
    analogs = []
    for r in raw_results:
        db_match = await _db_lookup(r.analog_article, db, segment)
        analogs.append(AnalogItem(
            analog_article=r.analog_article,
            analog_name=r.analog_name,
            source=r.source,
            db_match=db_match,
        ))

    return AnalogSearchResponse(
        analogs=analogs,
        cached=False,
        provider_error=error,
    )
