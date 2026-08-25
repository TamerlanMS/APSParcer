import logging
import asyncio
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.core.database import get_db
from app.core.security import verify_api_key, verify_any_auth, get_current_user_optional
from app.core.audit import write_audit
from app.core.config import settings
from app.models.models import (
    Product, BrandConstant, CurrencyRate, ImportLog, Manager,
    AppSetting, DEFAULT_APP_SETTINGS,
)
from app.services.db_importer import (
    import_products_from_excel, import_constants_from_excel,
    clear_segment_products, get_segment_stats,
)
from app.services.matcher import invalidate_product_cache
from app.services.excel_cache import rebuild_base_template, CACHE_PATH, TEMPLATE_PATH
from pydantic import BaseModel
from typing import Optional, List
import bcrypt

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Schemas ───────────────────────────────────────────────────────────────────

class ProductUpdate(BaseModel):
    article:  Optional[str]   = None
    name:     Optional[str]   = None
    unit:     Optional[str]   = None
    kaznisa:  Optional[float] = None
    rrts:     Optional[float] = None
    mrc:      Optional[float] = None
    opt:      Optional[float] = None
    partner:  Optional[float] = None
    brand:    Optional[str]   = None
    is_active: Optional[bool] = None


class ConstantUpdate(BaseModel):
    margin:        Optional[float] = None
    logistics:     Optional[float] = None
    rate:          Optional[float] = None
    currency_rate: Optional[float] = None
    nds:           Optional[float] = None
    gp:            Optional[float] = None


class AdminRequest(BaseModel):
    password: str


# ─── Helpers ───────────────────────────────────────────────────────────────────

def require_import_auth(current_user, password: str):
    """Пропускает импорт при действующей сессии либо по паролю админа.

    Клиент пароль не запрашивает и присылает пустую строку, поэтому без
    сессии нужно сообщать именно об этом: токен живёт 12 часов, сессия
    может быть отозвана, пользователь — деактивирован. Раньше в таких
    случаях выдавалось «Неверный пароль администратора», что уводило
    от настоящей причины.
    """
    if current_user is not None:
        return
    if password:
        check_admin(password)
        return
    raise HTTPException(
        401,
        "Сессия истекла или была завершена. Выйдите и войдите в систему заново.",
    )


def check_admin(password: str):
    try:
        ok = bcrypt.checkpw(password.encode(), settings.ADMIN_PASSWORD_HASH.encode())
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(403, "Неверный пароль администратора")


# ─── Products CRUD ─────────────────────────────────────────────────────────────

@router.get("/products")
async def list_products(
    brand: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    q = select(Product).where(Product.is_active == True)
    if brand:
        q = q.where(Product.brand == brand)
    if search:
        like = f"%{search}%"
        q = q.where(
            Product.article.ilike(like) | Product.name.ilike(like)
        )
    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    products = result.scalars().all()
    return [
        {
            "id": p.id, "num": p.num, "article": p.article, "name": p.name,
            "unit": p.unit, "brand": p.brand, "kaznisa": p.kaznisa,
            "rrts": p.rrts, "mrc": p.mrc, "opt": p.opt, "partner": p.partner,
            "multiplicity": p.multiplicity, "kaznisa_code": p.kaznisa_code,
        }
        for p in products
    ]


@router.get("/products/count")
async def count_products(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    result = await db.execute(
        select(func.count()).select_from(Product).where(Product.is_active == True)
    )
    return {"count": result.scalar()}


@router.get("/products/all")
async def list_all_products(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    """Возвращает все активные товары без пагинации (для заполнения листа БД в Excel)."""
    result = await db.execute(
        select(Product).where(Product.is_active == True).order_by(Product.num)
    )
    products = result.scalars().all()
    return [
        {
            "id": p.id, "num": p.num, "article": p.article, "name": p.name,
            "unit": p.unit, "brand": p.brand, "kaznisa": p.kaznisa,
            "rrts": p.rrts, "mrc": p.mrc, "opt": p.opt, "partner": p.partner,
            "multiplicity": p.multiplicity, "kaznisa_code": p.kaznisa_code,
        }
        for p in products
    ]


@router.patch("/products/{product_id}")
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Товар не найден")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(product, field, value)

    await db.commit()
    return {"status": "updated", "id": product_id}


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    body: AdminRequest,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    check_admin(body.password)
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Товар не найден")
    product.is_active = False
    await db.commit()
    return {"status": "deleted"}


# ─── Import ────────────────────────────────────────────────────────────────────

def _check_excel_file(file: UploadFile):
    name = (file.filename or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
        raise HTTPException(400, "Файл должен быть в формате .xlsx или .xlsm")


def _is_admin_user(user) -> bool:
    """True если у пользователя роль admin/superadmin."""
    try:
        return user is not None and user.role.name.value in ("superadmin", "administrator")
    except Exception:
        return False


@router.post("/import/products")
async def import_products(
    request: Request,
    file: UploadFile = File(...),
    password: str = Query(default=""),
    segment: Optional[str] = Query(default=None, description="Сегмент для импорта: ss/os/sil"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    # Действующая сессия либо пароль админа (совместимость со старым клиентом)
    require_import_auth(current_user, password)
    _check_excel_file(file)

    # Определяем сегмент для импорта
    if segment:
        import_segment = segment
    elif current_user is not None and not _is_admin_user(current_user):
        # Менеджер может импортировать только свой сегмент
        import_segment = getattr(current_user, "segment", None) or "ss"
    else:
        # Admin/superadmin без явного segment — default ss (или переданный)
        import_segment = "ss"

    # Непривилегированный пользователь не может импортировать чужой сегмент
    if (current_user is not None
            and not _is_admin_user(current_user)
            and segment
            and segment != getattr(current_user, "segment", "ss")):
        raise HTTPException(403, f"Нельзя импортировать в чужой сегмент ({segment})")

    content = await file.read()
    ip = request.client.host if request.client else None
    try:
        added, updated = await import_products_from_excel(
            content, db, file.filename, segment=import_segment,
            changed_by=getattr(current_user, "username", ""),
        )
    except ValueError as e:
        await write_audit(db, current_user, "import_products",
                          resource=file.filename, details=str(e), ip=ip, status="error")
        raise HTTPException(422, str(e))
    await write_audit(db, current_user, "import_products",
                      resource=file.filename,
                      details=f"added={added}, updated={updated}",
                      ip=ip)
    # Сохраняем загруженный файл как мастер-шаблон для следующих rebuild
    try:
        os.makedirs(os.path.dirname(TEMPLATE_PATH), exist_ok=True)
        with open(TEMPLATE_PATH, "wb") as _tf:
            _tf.write(content)
        logger.info("database: saved new WV template (%d bytes)", len(content))
    except Exception as _te:
        logger.warning("database: could not save template: %s", _te)
    # Инвалидировать кэш товаров — следующий PDF-матчинг перечитает из БД
    invalidate_product_cache()
    # Rebuild cached base template in background (non-blocking)
    asyncio.create_task(rebuild_base_template(db))
    return {"status": "ok", "added": added, "updated": updated}


@router.post("/import/constants")
async def import_constants(
    request: Request,
    file: UploadFile = File(...),
    password: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    # Действующая сессия либо пароль админа (совместимость со старым клиентом)
    require_import_auth(current_user, password)
    _check_excel_file(file)
    content = await file.read()
    ip = request.client.host if request.client else None
    try:
        count = await import_constants_from_excel(content, db, file.filename)
    except ValueError as e:
        await write_audit(db, current_user, "import_constants",
                          resource=file.filename, details=str(e), ip=ip, status="error")
        raise HTTPException(422, str(e))
    await write_audit(db, current_user, "import_constants",
                      resource=file.filename,
                      details=f"brands_updated={count}",
                      ip=ip)
    # Rebuild cached base template in background (non-blocking)
    asyncio.create_task(rebuild_base_template(db))
    return {"status": "ok", "brands_updated": count}


# ─── Manual vectorization ─────────────────────────────────────────────────────

@router.get("/embed-budget")
async def get_embed_budget(
    _auth: str = Depends(verify_any_auth),
):
    """Возвращает состояние дневного бюджета на векторизацию (OpenAI embeddings)."""
    from app.services.embedder import get_budget_snapshot
    return get_budget_snapshot()


@router.get("/pinecone/status")
async def pinecone_status(
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Проверяет подключение к Pinecone и возвращает статистику индекса."""
    if not _is_admin_user(current_user):
        raise HTTPException(403, "Требуются права администратора")
    from app.services.embedder import test_pinecone_connection
    return await test_pinecone_connection()


@router.post("/pinecone/reconnect")
async def pinecone_reconnect(
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Сбрасывает кешированный Pinecone-клиент и переподключается с текущими ключами.
    Используй после обновления PINECONE_API_KEY / PINECONE_HOST в .env без перезапуска."""
    if not _is_admin_user(current_user):
        raise HTTPException(403, "Требуются права администратора")
    from app.services.embedder import reset_pinecone_client, test_pinecone_connection
    reset_pinecone_client()
    result = await test_pinecone_connection()
    logger.info("pinecone/reconnect by %s: ok=%s", getattr(current_user, "username", "?"), result.get("ok"))
    return {"reconnected": True, "test": result}


@router.post("/vectorize")
async def start_vectorization(
    segment: Optional[str] = Query(default=None, description="Сегмент для векторизации: ss/os/sil или all"),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """
    Запускает векторизацию товаров в Pinecone (только admin/superadmin).

    Сегменты обрабатываются строго последовательно (SS → OS → SIL).
    Перед каждым батчем проверяется дневной бюджет ($EMBED_DAILY_BUDGET_USD).
    Если бюджет исчерпан — оставшиеся позиции пропускаются.
    """
    if not _is_admin_user(current_user):
        raise HTTPException(403, "Требуются права администратора")

    from app.core.database import AsyncSessionLocal
    from app.services.embedder import embed_products_batch, get_budget_snapshot
    from app.models.models import ALL_SEGMENTS

    segs = ALL_SEGMENTS if (not segment or segment == "all") else [segment]

    # Accumulate results from all segments for progress tracking
    _results: list[dict] = []

    async def _run():
        for seg in segs:
            logger.info("vectorize: starting segment=%s", seg)
            res = await embed_products_batch(AsyncSessionLocal, segment=seg, force=True)
            _results.append({"segment": seg, **res})
            logger.info(
                "vectorize: segment=%s done — upserted=%d skipped=%d "
                "cost=$%.5f budget_remaining=$%.5f budget_exceeded=%s",
                seg,
                res.get("upserted", 0), res.get("skipped", 0),
                res.get("cost_usd", 0.0), res.get("budget_remaining", 0.0),
                res.get("budget_exceeded", False),
            )
            if res.get("budget_exceeded"):
                logger.warning("vectorize: daily budget exceeded — stopping after %s", seg)
                break   # stop processing further segments

    asyncio.create_task(_run())
    logger.info("vectorize: manual start segments=%s by user=%s",
                segs, getattr(current_user, "username", "?"))
    budget = get_budget_snapshot()
    return {
        "status":   "started",
        "segments": segs,
        "message":  (
            f"Векторизация сегментов {segs} запущена последовательно. "
            f"Бюджет: ${budget['budget_usd']:.2f} / потрачено сегодня: "
            f"${budget['spent_usd']:.4f} / остаток: ${budget['remaining_usd']:.4f}"
        ),
        "budget": budget,
    }


# ─── Base template download ────────────────────────────────────────────────────

@router.get("/base-template")
async def get_base_template(
    _key: str = Depends(verify_api_key),
):
    """Download pre-built .xlsm with БД and Const sheets already filled.

    Rebuilt automatically after every products/constants import.
    Returns 404 if no import has been run yet.
    """
    if not os.path.exists(CACHE_PATH):
        raise HTTPException(
            404,
            "Кэшированный шаблон не найден. Выполните импорт товаров или констант."
        )
    return FileResponse(
        CACHE_PATH,
        media_type="application/vnd.ms-excel.sheet.macroEnabled.12",
        filename="base_template.xlsm",
    )



# ─── Segment stats & clear ───────────────────────────────────────────────────

@router.get("/stats")
async def db_stats(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    """Возвращает количество активных товаров по каждому сегменту (ss / os / sil / total)."""
    stats = await get_segment_stats(db)
    return stats


@router.delete("/segment/{segment}")
async def clear_segment(
    segment: str,
    hard: bool = Query(default=False, description="True = физическое удаление строк"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """
    Очищает базу товаров для указанного сегмента (ss / os / sil).
    Требует прав администратора.
    hard=false → деактивация (is_active=False), данные сохраняются
    hard=true  → физическое удаление строк из БД
    """
    if not _is_admin_user(current_user):
        raise HTTPException(403, "Требуются права администратора")
    valid = ("ss", "os", "sil", "gen")
    if segment not in valid:
        raise HTTPException(400, f"Недопустимый сегмент. Доступны: {', '.join(valid)}")

    count = await clear_segment_products(
        db, segment, hard_delete=hard,
        changed_by=getattr(current_user, "username", ""),
    )
    invalidate_product_cache()
    asyncio.create_task(rebuild_base_template(db))

    action = "удалено" if hard else "деактивировано"
    logger.info("clear_segment[%s]: %d products %s by %s",
                segment, count, action,
                getattr(current_user, "username", "?"))
    return {"status": "ok", "segment": segment, "affected": count, "action": action}


# ─── Product price lookup (diagnostic) ───────────────────────────────────────

@router.get("/products/search")
async def search_products(
    q:            str = Query(default="", description="Единый поиск: артикул / наименование / код КазНИИСА"),
    article:      str = Query(default="", description="Поиск только по артикулу (legacy)"),
    name:         str = Query(default="", description="Поиск только по названию (legacy)"),
    kaznisa_code: str = Query(default="", description="Поиск по коду КазНИИСА"),
    segment:      str = Query(default="", description="Фильтр по сегменту: ss / os / sil"),
    limit:        int = Query(default=30, ge=1, le=100),
    db:           AsyncSession = Depends(get_db),
    _auth:        str = Depends(verify_any_auth),
):
    """
    Единый поиск товаров — ищет одновременно по артикулу, наименованию и коду КазНИИСА.
    - q=           → ищет во всех трёх полях (OR)
    - kaznisa_code → дополнительный фильтр по коду
    - segment=     → фильтр по сегменту (ss / os / sil); пусто = все сегменты
    Используется в ArticleSearchDialog.
    """
    from sqlalchemy import or_, and_

    qry  = (q            or "").strip()
    art  = (article      or "").strip()
    nm   = (name         or "").strip()
    code = (kaznisa_code or "").strip()
    seg  = (segment      or "").strip().lower()

    if not qry and not art and not nm and not code:
        return {"products": [], "total": 0}

    conditions = []
    order_extra = []

    # Основной поиск: q ищет во всех трёх полях одновременно (OR)
    if qry:
        conditions.append(or_(
            Product.article.ilike(f"%{qry}%"),
            Product.name.ilike(f"%{qry}%"),
            Product.kaznisa_code.ilike(f"%{qry}%"),
        ))
        order_extra += [
            (func.lower(Product.article) == qry.lower()).desc(),
            Product.article.ilike(f"{qry}%").desc(),
            (func.lower(Product.kaznisa_code) == qry.lower()).desc(),
        ]

    # Legacy: отдельные поля article= и name=
    if not qry and art:
        conditions.append(Product.article.ilike(f"%{art}%"))
        order_extra += [
            (func.lower(Product.article) == art.lower()).desc(),
            Product.article.ilike(f"{art}%").desc(),
        ]
    if not qry and nm:
        conditions.append(Product.name.ilike(f"%{nm}%"))

    # Дополнительный фильтр по коду КазНИИСА
    if code:
        conditions.append(Product.kaznisa_code.ilike(f"%{code}%"))

    if not conditions:
        return {"products": [], "total": 0}

    # AND между условиями (сужаем)
    where_clause = and_(*conditions) if len(conditions) > 1 else conditions[0]

    stmt = select(Product).where(Product.is_active == True, where_clause)

    # Фильтр по сегменту
    if seg and seg in ("ss", "os", "sil", "gen"):
        stmt = stmt.where(Product.segment == seg)

    if order_extra:
        stmt = stmt.order_by(*order_extra)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    prods = result.scalars().all()
    return {
        "products": [
            {
                "id":           p.id,
                "article":      p.article or "",
                "name":         p.name or "",
                "brand":        p.brand or "",
                "unit":         p.unit or "шт.",
                "kaznisa":      p.kaznisa,
                "rrts":         p.rrts,
                "mrc":          p.mrc,
                "opt":          p.opt,
                "partner":      p.partner,
                "multiplicity": p.multiplicity,
                "kaznisa_code": p.kaznisa_code or "",
            }
            for p in prods
        ],
        "total": len(prods),
    }


@router.get("/products/prices")
async def get_product_prices(
    articles: str = Query(default="", description="Comma-separated list of articles"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    """Return price fields for specified product articles. Used for diagnostics."""
    if not articles:
        return {"products": []}
    art_list = [a.strip() for a in articles.split(",") if a.strip()]
    result = await db.execute(
        select(Product).where(Product.article.in_(art_list))
    )
    prods = result.scalars().all()
    return {
        "products": [
            {
                "article":  p.article,
                "name":     p.name,
                "brand":    p.brand,
                "kaznisa":  p.kaznisa,
                "rrts":     p.rrts,
                "mrc":      p.mrc,
                "opt":      p.opt,
                "partner":  p.partner,
            }
            for p in prods
        ]
    }

# ─── Constants ─────────────────────────────────────────────────────────────────

@router.get("/constants")
async def get_constants(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    brands = await db.execute(select(BrandConstant))
    currencies = await db.execute(select(CurrencyRate))
    managers = await db.execute(
        select(Manager).where(Manager.is_active == True).order_by(Manager.full_name)
    )
    managers_list = managers.scalars().all()
    return {
        "brands": [
            {"brand": b.brand, "margin": b.margin, "logistics": b.logistics,
             "rate": b.rate, "currency_rate": b.currency_rate, "nds": b.nds, "gp": b.gp}
            for b in brands.scalars().all()
        ],
        "currencies": [
            {"name": c.name, "rate": c.rate}
            for c in currencies.scalars().all()
        ],
        "managers": [
            m.full_name for m in managers_list if m.full_name
        ],
        "managers_full": [
            {
                "full_name": m.full_name or "",
                "position":  m.position  or "",
                "email":     m.email     or "",
                "phone":     m.phone     or "",
            }
            for m in managers_list if m.full_name
        ],
    }


@router.patch("/constants/{brand}")
async def update_constant(
    brand: str,
    data: ConstantUpdate,
    password: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    check_admin(password)
    result = await db.execute(select(BrandConstant).where(BrandConstant.brand == brand))
    bc = result.scalar_one_or_none()
    if not bc:
        raise HTTPException(404, f"Бренд '{brand}' не найден")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(bc, field, value)
    await db.commit()
    return {"status": "updated", "brand": brand}


# ─── Brand statistics ─────────────────────────────────────────────────────────

@router.get("/brands/stats")
async def brands_stats(
    segment: Optional[str] = Query(default=None, description="Фильтр по сегменту: ss/os/sil"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    """Количество активных позиций по брендам с разбивкой по сегментам.
    Возвращает список, отсортированный по убыванию суммарного кол-ва позиций.
    """
    stmt = (
        select(Product.brand, Product.segment, func.count().label("cnt"))
        .where(Product.is_active == True, Product.brand.isnot(None))
        .group_by(Product.brand, Product.segment)
        .order_by(Product.brand)
    )
    if segment and segment in ("ss", "os", "sil", "gen"):
        stmt = stmt.where(Product.segment == segment)

    result = await db.execute(stmt)
    rows = result.fetchall()

    brands: dict = {}
    for brand, seg, cnt in rows:
        if brand not in brands:
            brands[brand] = {"brand": brand, "ss": 0, "os": 0,
                             "sil": 0, "gen": 0, "total": 0}
        if seg in ("ss", "os", "sil", "gen"):
            brands[brand][seg] = cnt
        brands[brand]["total"] += cnt

    return sorted(brands.values(), key=lambda x: x["total"], reverse=True)


# ─── Сверка с прейскурантом АГСК ───────────────────────────────────────────────

MAX_PRICELIST_SIZE = 120 * 1024 * 1024        # 120 МБ
_PRICELIST_EXECUTOR = ThreadPoolExecutor(max_workers=2,
                                         thread_name_prefix="pricelist")


@router.post("/pricelist/compare")
async def pricelist_compare(
    request: Request,
    file: UploadFile = File(...),
    segments: Optional[str] = Query("ss", description="Сегменты: ss / os / sil / all"),
    threshold: float = Query(5.0, description="Порог отклонения, %"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Сверяет цены КазНИИСА в базе со сметными ценами прейскуранта.

    Сопоставление строго по коду АГСК. Прогресс отдаётся событиями SSE,
    последнее событие содержит строки сверки и сводку.
    """
    fname = file.filename or "pricelist.pdf"
    if not fname.lower().endswith(".pdf"):
        raise HTTPException(400, "Прейскурант должен быть в формате PDF")

    content = await file.read()
    if len(content) > MAX_PRICELIST_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 120 МБ)")

    ip   = request.client.host if request.client else None
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    all_segs = ["ss", "os", "sil", "gen"]
    if not segments or segments.strip().lower() == "all":
        seg_list = all_segs
    else:
        seg_list = [s.strip().lower() for s in segments.split(",")
                    if s.strip().lower() in all_segs] or ["ss"]

    def _progress(pct: int, msg: str, stage: str = "parse") -> None:
        payload = json.dumps({"pct": pct, "stage": stage, "msg": msg},
                             ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def _process() -> None:
        tmp_path = ""
        try:
            _progress(2, "Файл получен, открываем прейскурант...", "upload")
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(tmp_fd)
            with open(tmp_path, "wb") as fh:
                fh.write(content)

            from app.services.pricelist_parser import (
                parse_pricelist_pdf, compare_with_products,
            )
            from app.services.matcher import get_products_for_segments

            # Разбор PDF — блокирующий, уводим в поток.
            # Прогресс парсера занимает шкалу 0-85%.
            def _parse():
                return parse_pricelist_pdf(
                    tmp_path,
                    progress_cb=lambda p, m: _progress(int(p * 0.85), m),
                )

            pricelist = await loop.run_in_executor(_PRICELIST_EXECUTOR, _parse)
            if not pricelist:
                await queue.put(json.dumps(
                    {"error": "В файле не найдено ни одного кода АГСК с ценой. "
                              "Проверьте, что это прейскурант КазНИИСА."},
                    ensure_ascii=False))
                return

            _progress(88, f"Загрузка товаров сегментов: {', '.join(seg_list)}...",
                      "load")
            products = await get_products_for_segments(db, seg_list)

            _progress(94, f"Сверка {len(products)} товаров...", "compare")
            result = compare_with_products(pricelist, products,
                                           threshold_pct=float(threshold))
            result["stats"]["segments"] = seg_list
            result["stats"]["filename"] = fname

            await write_audit(db, current_user, "pricelist_compare",
                              resource=fname,
                              details=(f"codes={len(pricelist)}, "
                                       f"matched={result['stats']['matched']}, "
                                       f"over={result['stats']['over_threshold']}"),
                              ip=ip)

            _progress(99, "Готово", "done")
            await queue.put(json.dumps({"done": True, "result": result},
                                       ensure_ascii=False))

        except Exception as exc:
            logger.exception("pricelist compare failed: %s", exc)
            await write_audit(db, current_user, "pricelist_compare",
                              resource=fname, details=str(exc),
                              ip=ip, status="error")
            await queue.put(json.dumps({"error": f"Ошибка: {exc}"},
                                       ensure_ascii=False))
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    asyncio.create_task(_process())

    async def _events():
        while True:
            data = await queue.get()
            yield "data: " + data + "\n\n"
            parsed = json.loads(data)
            if "done" in parsed or "error" in parsed:
                break

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/pricelist/parse")
async def pricelist_parse(
    request: Request,
    file: UploadFile = File(...),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Разбирает прейскурант и отдаёт позиции клиенту.

    Отличие от /pricelist/compare: база из БД не читается — сверка идёт с
    эксель-файлом на стороне клиента. Прогресс тот же, событиями SSE.
    """
    fname = file.filename or "pricelist.pdf"
    if not fname.lower().endswith(".pdf"):
        raise HTTPException(400, "Прейскурант должен быть в формате PDF")

    content = await file.read()
    if len(content) > MAX_PRICELIST_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 120 МБ)")

    loop  = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _progress(pct: int, msg: str, stage: str = "parse") -> None:
        queue.put_nowait(json.dumps({"pct": pct, "stage": stage, "msg": msg},
                                    ensure_ascii=False))

    def _progress_ts(pct: int, msg: str) -> None:
        loop.call_soon_threadsafe(_progress, pct, msg)

    async def _process() -> None:
        tmp_path = ""
        try:
            _progress(2, "Файл получен, открываем прейскурант...", "upload")
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(tmp_fd)
            with open(tmp_path, "wb") as fh:
                fh.write(content)

            from app.services.pricelist_parser import parse_pricelist_pdf

            def _parse():
                return parse_pricelist_pdf(
                    tmp_path,
                    progress_cb=lambda p, m: _progress_ts(int(p * 0.97), m),
                )

            entries = await loop.run_in_executor(_PRICELIST_EXECUTOR, _parse)
            if not entries:
                await queue.put(json.dumps(
                    {"error": "В файле не найдено ни одного кода АГСК с ценой. "
                              "Проверьте, что это прейскурант КазНИИСА."},
                    ensure_ascii=False))
                return

            _progress(99, f"Разобрано позиций: {len(entries):,}", "done")
            await queue.put(json.dumps(
                {"done": True,
                 "result": {"entries": entries, "count": len(entries),
                            "filename": fname}},
                ensure_ascii=False))
        except Exception as exc:
            logger.exception("pricelist parse failed: %s", exc)
            await queue.put(json.dumps({"error": f"Ошибка: {exc}"},
                                       ensure_ascii=False))
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    asyncio.create_task(_process())

    async def _events():
        while True:
            data = await queue.get()
            yield "data: " + data + "\n\n"
            parsed = json.loads(data)
            if "done" in parsed or "error" in parsed:
                break

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class GeneralItem(BaseModel):
    """Позиция прейскуранта, не найденная ни в одной сегментной базе."""
    kaznisa_code: str
    name:         str = ""
    unit:         str = "шт."
    kaznisa:      Optional[float] = None


class GeneralUpload(BaseModel):
    items: List[GeneralItem]


@router.post("/pricelist/to-general")
async def pricelist_to_general(
    request: Request,
    payload: GeneralUpload,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Кладёт несовпавшие позиции прейскуранта в общую базу (сегмент gen).

    Артикул остаётся пустым — у прейскуранта его нет. Уникальность держится
    на коде АГСК, поэтому повторный прогон обновляет цену существующей
    записи вместо создания дубля.
    """
    require_import_auth(current_user, "")

    items = [i for i in payload.items if (i.kaznisa_code or "").strip()]
    if not items:
        return {"status": "ok", "added": 0, "updated": 0}

    codes = {i.kaznisa_code.strip() for i in items}
    existing = await db.execute(
        select(Product.kaznisa_code, Product.id)
        .where(Product.segment == "gen", Product.kaznisa_code.in_(codes))
    )
    by_code = {row[0]: row[1] for row in existing.fetchall() if row[0]}

    added = updated = 0
    seen: set = set()
    for it in items:
        code = it.kaznisa_code.strip()
        if code in seen:                 # дубль внутри одной выгрузки
            continue
        seen.add(code)
        data = dict(
            name=(it.name or "").strip() or None,
            unit=(it.unit or "шт.").strip(),
            kaznisa=it.kaznisa,
            kaznisa_code=code,
            segment="gen",
            is_active=True,
        )
        if code in by_code:
            await db.execute(
                update(Product).where(Product.id == by_code[code]).values(**data)
            )
            updated += 1
        else:
            db.add(Product(article=None, **data))
            added += 1

    await db.commit()

    ip = request.client.host if request.client else None
    await write_audit(db, current_user, "pricelist_to_general",
                      resource="Общая база (АГСК)",
                      details=f"added={added}, updated={updated}", ip=ip)

    invalidate_product_cache()
    logger.info("pricelist_to_general: added=%d updated=%d by %s",
                added, updated, getattr(current_user, "username", "?"))
    return {"status": "ok", "added": added, "updated": updated}


# ─── App Settings ──────────────────────────────────────────────────────────────

class AppSettingsUpdate(BaseModel):
    prelim_price_coeff: Optional[float] = None


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Читает значение настройки; если записи нет — возвращает default."""
    res = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = res.scalar_one_or_none()
    if row is None or row.value is None:
        return default
    return row.value


@router.get("/settings")
async def get_app_settings(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    """Глобальные настройки приложения. Доступно всем авторизованным."""
    raw = await _get_setting(
        db, "prelim_price_coeff",
        DEFAULT_APP_SETTINGS["prelim_price_coeff"][0],
    )
    try:
        coeff = float(raw)
    except (TypeError, ValueError):
        coeff = float(DEFAULT_APP_SETTINGS["prelim_price_coeff"][0])
    if coeff <= 0:
        coeff = float(DEFAULT_APP_SETTINGS["prelim_price_coeff"][0])
    return {"prelim_price_coeff": coeff}


@router.put("/settings")
async def update_app_settings(
    body: AppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Изменение глобальных настроек — только admin/superadmin."""
    if not _is_admin_user(current_user):
        raise HTTPException(403, "Требуются права администратора")

    updated = {}
    if body.prelim_price_coeff is not None:
        coeff = float(body.prelim_price_coeff)
        if coeff <= 0:
            raise HTTPException(400, "Коэффициент должен быть больше нуля")

        res = await db.execute(
            select(AppSetting).where(AppSetting.key == "prelim_price_coeff")
        )
        row = res.scalar_one_or_none()
        username = getattr(current_user, "username", None)
        if row is None:
            row = AppSetting(
                key="prelim_price_coeff",
                description=DEFAULT_APP_SETTINGS["prelim_price_coeff"][1],
            )
            db.add(row)
        row.value      = str(coeff)
        row.updated_by = username
        updated["prelim_price_coeff"] = coeff

        await db.commit()
        logger.info("app_settings updated by %s: %s", username, updated)

    return {"updated": updated}


# ─── Import Logs ───────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_import_logs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_any_auth),
):
    result = await db.execute(
        select(ImportLog).order_by(ImportLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id":           l.id,
            "filename":     l.filename,
            "segment":      l.segment or "",
            "action":       l.action or "import",
            "rows_added":   l.rows_added,
            "rows_updated": l.rows_updated,
            "count_before": l.count_before,
            "count_after":  l.count_after,
            "changed_by":   l.changed_by or "",
            "status":       l.status,
            "message":      l.message,
            "created_at":   str(l.created_at),
        }
        for l in logs
    ]
