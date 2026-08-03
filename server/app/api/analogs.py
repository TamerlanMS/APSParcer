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
from app.models.models import Product, ProductAnalog, AnalogDatabase
from app.services.analog_providers import PROVIDERS, _ekf_last_error, _ekf_jwt
from app.core.config import settings

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


# ─── Analog Database CRUD ─────────────────────────────────────────────────────

class AnalogDBSaveRequest(BaseModel):
    article:        str
    analog_article: str
    segment:        Optional[str] = None
    analog_name:    Optional[str] = None
    analog_brand:   Optional[str] = None
    source:         str = "manual"
    notes:          Optional[str] = None


class AnalogDBLookupRequest(BaseModel):
    articles: list[str]
    segment:  Optional[str] = None


@router.get("/db")
async def get_analog_db(
    article: str,
    segment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """GET /api/v1/analogs/db?article=xxx&segment=ss — запись аналога из постоянной базы."""
    stmt = (
        select(AnalogDatabase)
        .where(AnalogDatabase.article == article.strip())
        .where(AnalogDatabase.is_active == True)  # noqa: E712
    )
    if segment:
        stmt = stmt.where(AnalogDatabase.segment == segment)
    stmt = stmt.order_by(AnalogDatabase.created_at.desc()).limit(1)
    q = await db.execute(stmt)
    rec = q.scalars().first()
    if not rec:
        return {"found": False, "record": None}
    return {
        "found": True,
        "record": {
            "id":             rec.id,
            "article":        rec.article,
            "segment":        rec.segment,
            "analog_article": rec.analog_article,
            "analog_name":    rec.analog_name,
            "analog_brand":   rec.analog_brand,
            "source":         rec.source,
            "notes":          rec.notes,
            "added_by":       rec.added_by,
            "created_at":     rec.created_at.isoformat() if rec.created_at else None,
        },
    }


@router.post("/db/lookup")
async def lookup_analogs_batch(
    body: AnalogDBLookupRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """POST /api/v1/analogs/db/lookup — пакетный поиск аналогов для списка артикулов."""
    articles = [a.strip() for a in body.articles if a and a.strip()]
    if not articles:
        return {"analogs": {}}

    stmt = (
        select(AnalogDatabase)
        .where(AnalogDatabase.article.in_(articles))
        .where(AnalogDatabase.is_active == True)  # noqa: E712
        .order_by(AnalogDatabase.created_at.desc())
    )
    if body.segment:
        stmt = stmt.where(AnalogDatabase.segment == body.segment)

    q = await db.execute(stmt)
    rows = q.scalars().all()

    # article → first (newest) record
    result: dict[str, dict] = {}
    for rec in rows:
        if rec.article not in result:
            result[rec.article] = {
                "id":             rec.id,
                "analog_article": rec.analog_article,
                "analog_name":    rec.analog_name,
                "analog_brand":   rec.analog_brand,
                "source":         rec.source,
                "added_by":       rec.added_by,
            }
    return {"analogs": result}


@router.post("/db")
async def save_analog_db(
    body: AnalogDBSaveRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """POST /api/v1/analogs/db — сохранить / обновить аналог для артикула."""
    article = body.article.strip()

    # Upsert: если запись для этого артикула (+сегмента) уже есть — обновить
    stmt = (
        select(AnalogDatabase)
        .where(AnalogDatabase.article == article)
        .where(AnalogDatabase.is_active == True)  # noqa: E712
    )
    if body.segment:
        stmt = stmt.where(AnalogDatabase.segment == body.segment)
    stmt = stmt.order_by(AnalogDatabase.created_at.desc()).limit(1)
    q = await db.execute(stmt)
    rec = q.scalars().first()

    if rec:
        rec.analog_article = body.analog_article.strip()
        rec.analog_name    = body.analog_name
        rec.analog_brand   = body.analog_brand
        rec.source         = body.source
        rec.notes          = body.notes
        rec.added_by       = getattr(user, "username", None)
    else:
        rec = AnalogDatabase(
            article        = article,
            segment        = body.segment,
            analog_article = body.analog_article.strip(),
            analog_name    = body.analog_name,
            analog_brand   = body.analog_brand,
            source         = body.source,
            notes          = body.notes,
            added_by       = getattr(user, "username", None),
        )
        db.add(rec)

    await db.commit()
    await db.refresh(rec)
    return {"ok": True, "id": rec.id, "analog_article": rec.analog_article}


@router.delete("/db/{record_id}")
async def delete_analog_db(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """DELETE /api/v1/analogs/db/{id} — деактивировать запись аналога."""
    q = await db.execute(select(AnalogDatabase).where(AnalogDatabase.id == record_id))
    rec = q.scalars().first()
    if not rec:
        return {"ok": False, "detail": "not found"}
    rec.is_active = False
    await db.commit()
    return {"ok": True}


# ─── Diagnostic endpoint ──────────────────────────────────────────────────────

@router.get("/diagnostics")
async def diagnostics(_user=Depends(get_current_user)):
    """Проверяет конфигурацию и связь с провайдерами аналогов.
    Возвращает статус каждого провайдера без выполнения реального поиска."""
    import httpx as _httpx

    result: dict = {"providers": {}, "connectivity": {}}

    # ── Проверяем настройки провайдеров ──────────────────────────────────────
    ekf_user   = getattr(settings, "EKF_USERNAME", "")
    ekf_pass   = getattr(settings, "EKF_PASSWORD", "")
    ekf_cookie = getattr(settings, "EKF_COOKIE", "")
    ekf_key    = getattr(settings, "EKF_API_KEY", "")
    dkc_key    = getattr(settings, "DKC_API_KEY", "")
    iek_cookie = getattr(settings, "IEK_COOKIE", "")

    from app.services.analog_providers import _ekf_jwt as jwt_cached, _ekf_last_error as last_err

    result["providers"]["ekf"] = {
        "credentials_set": bool(ekf_user and ekf_pass) or bool(ekf_cookie) or bool(ekf_key),
        "login_password":  bool(ekf_user and ekf_pass),
        "cookie_set":      bool(ekf_cookie),
        "api_key_set":     bool(ekf_key),
        "jwt_cached":      bool(jwt_cached),
        "last_error":      last_err,
    }
    result["providers"]["dkc"] = {"credentials_set": bool(dkc_key)}
    result["providers"]["iek"] = {"credentials_set": bool(iek_cookie)}

    # ── Проверяем сетевую связь ───────────────────────────────────────────────
    test_urls = {
        "hasura.ekfgroup.com": "https://hasura.ekfgroup.com/healthz",
        "ekfgroup.com":        "https://ekfgroup.com/",
    }
    async with _httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for name, url in test_urls.items():
            try:
                r = await client.get(url)
                result["connectivity"][name] = {"ok": True, "status": r.status_code}
            except _httpx.ConnectError as e:
                result["connectivity"][name] = {"ok": False, "error": f"ConnectError: {e}"}
            except _httpx.TimeoutException:
                result["connectivity"][name] = {"ok": False, "error": "timeout (>8s)"}
            except Exception as e:
                result["connectivity"][name] = {"ok": False, "error": str(e)}

    return result
