"""
API /suppliers/* — импорт прайсов поставщиков.
"""
from __future__ import annotations
import os
import tempfile
import logging

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database  import get_db
from app.core.security  import verify_any_auth
from app.models.models  import User
from app.services.price_import_service import (
    parse_and_diff,
    get_diff,
    confirm_import,
    get_price_history,
    list_suppliers,
    list_import_logs,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("/")
async def get_suppliers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(verify_any_auth),
):
    """Список известных поставщиков."""
    return await list_suppliers(db)


@router.get("/import-logs")
async def get_import_logs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(verify_any_auth),
):
    """История загрузок прайсов."""
    return await list_import_logs(db, limit=limit)


@router.post("/upload")
async def upload_pricelist(
    file: UploadFile = File(...),
    force_remap: bool = Query(False, description="Принудительно вызвать Claude API, игнорировать кэш"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(verify_any_auth),
):
    """
    Загрузить прайс-лист .xlsx.
    Claude API автоматически определяет структуру (с кэшированием).
    Возвращает job_id для последующего подтверждения.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Поддерживаются только .xlsx / .xls файлы")

    # Сохраняем во временный файл
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await parse_and_diff(
            db                = db,
            file_path         = tmp_path,
            original_filename = file.filename,
            force_remap       = force_remap,
            user_id           = current_user.id,
            username          = current_user.username,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if "error" in result:
        raise HTTPException(422, result.get("detail", result["error"]))

    return result


@router.get("/diff/{job_id}")
async def get_diff_report(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(verify_any_auth),
):
    """Полный отчёт о diff для указанного job_id."""
    result = await get_diff(db, job_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/confirm/{job_id}")
async def confirm_pricelist(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(verify_any_auth),
):
    """
    Подтвердить и применить изменения прайса к основной БД.
    Требует роли administrator или выше.
    """
    result = await confirm_import(db, job_id, user_id=current_user.id)
    if "error" in result:
        status_code = 404 if result["error"] == "not_found" else 409
        raise HTTPException(status_code, result["error"])
    return result


@router.get("/price-history/{article}")
async def price_history(
    article: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(verify_any_auth),
):
    """История изменений цен для артикула."""
    return await get_price_history(db, article, limit=limit)

