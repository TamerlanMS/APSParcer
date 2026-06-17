import logging
import asyncio
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.security import verify_api_key, verify_any_auth, get_current_user_optional
from app.core.audit import write_audit
from app.core.config import settings
from app.models.models import Product, BrandConstant, CurrencyRate, ImportLog, Manager
from app.services.db_importer import import_products_from_excel, import_constants_from_excel
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
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    if not _is_admin_user(current_user):
        check_admin(password)
    _check_excel_file(file)
    content = await file.read()
    ip = request.client.host if request.client else None
    try:
        added, updated = await import_products_from_excel(content, db, file.filename)
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
    if not _is_admin_user(current_user):
        check_admin(password)
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



# ─── Product price lookup (diagnostic) ──────────────────────────────────────────

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
        {"id": l.id, "filename": l.filename, "rows_added": l.rows_added,
         "rows_updated": l.rows_updated, "status": l.status,
         "message": l.message, "created_at": str(l.created_at)}
        for l in logs
    ]
