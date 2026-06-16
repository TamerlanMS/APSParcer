"""
API для управления Excel-шаблоном (.xlsm).

Эндпоинты:
  POST   /admin/excel-template          — загрузить новый шаблон (admin+)
  GET    /admin/excel-template          — информация о текущем шаблоне
  GET    /admin/excel-template/download — скачать текущий шаблон
  DELETE /admin/excel-template          — удалить из БД (откат на файловый шаблон)
"""

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin_up, get_current_user
from app.models.models import ExcelTemplate, User
from app.services.excel_cache import invalidate_base_template

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_SIZE = 20 * 1024 * 1024   # 20 МБ — разумный предел для .xlsm


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TemplateInfo(BaseModel):
    id:          int
    version:     int
    filename:    str
    file_size:   int
    file_hash:   str
    description: Optional[str]
    uploaded_by: Optional[str]   # имя пользователя
    uploaded_at: str
    is_active:   bool
    source:      str             # "database" | "filesystem"


class NoTemplateInfo(BaseModel):
    source: str = "filesystem"
    message: str = "В БД нет активного шаблона — используется WV_template.xlsm из assets"


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_active(db: AsyncSession) -> Optional[ExcelTemplate]:
    result = await db.execute(
        select(ExcelTemplate)
        .where(ExcelTemplate.is_active == True)
        .order_by(ExcelTemplate.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ─── Эндпоинты ────────────────────────────────────────────────────────────────

@router.post("/admin/excel-template", response_model=TemplateInfo)
async def upload_template(
    file:        UploadFile = File(...),
    description: str        = "",
    db:          AsyncSession = Depends(get_db),
    current_user: User      = Depends(require_admin_up),
):
    """Загрузить новый .xlsm шаблон. Старая версия деактивируется."""
    if not file.filename.lower().endswith(".xlsm"):
        raise HTTPException(400, "Файл должен быть в формате .xlsm")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "Файл пуст")
    if len(data) > MAX_SIZE:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_SIZE // 1_048_576} МБ)")

    file_hash = hashlib.sha256(data).hexdigest()

    # Проверяем — может уже загружен такой же файл
    existing = await _get_active(db)
    if existing and existing.file_hash == file_hash:
        raise HTTPException(409, "Этот шаблон уже является активным (хэш совпадает)")

    # Определяем новую версию
    result = await db.execute(select(ExcelTemplate.version).order_by(ExcelTemplate.version.desc()).limit(1))
    last_version = result.scalar_one_or_none() or 0
    new_version = last_version + 1

    # Деактивируем все старые
    await db.execute(
        update(ExcelTemplate).where(ExcelTemplate.is_active == True).values(is_active=False)
    )

    # Создаём новую запись
    tpl = ExcelTemplate(
        version     = new_version,
        filename    = file.filename,
        data        = data,
        file_size   = len(data),
        file_hash   = file_hash,
        description = description.strip() or None,
        uploaded_by = current_user.id,
        is_active   = True,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)

    # Сбрасываем кэш base_template — следующий запрос пересоберёт с новым шаблоном
    invalidate_base_template()
    logger.info(
        "excel_template: uploaded v%d '%s' by user_id=%d, size=%d bytes",
        new_version, file.filename, current_user.id, len(data),
    )

    uploader_name = current_user.full_name or current_user.username
    return TemplateInfo(
        id          = tpl.id,
        version     = tpl.version,
        filename    = tpl.filename,
        file_size   = tpl.file_size,
        file_hash   = tpl.file_hash,
        description = tpl.description,
        uploaded_by = uploader_name,
        uploaded_at = tpl.uploaded_at.isoformat() if tpl.uploaded_at else "",
        is_active   = tpl.is_active,
        source      = "database",
    )


@router.get("/admin/excel-template")
async def get_template_info(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_up),
):
    """Информация о текущем активном шаблоне."""
    tpl = await _get_active(db)
    if not tpl:
        return NoTemplateInfo()

    # Загружаем имя загрузчика
    uploader_name: Optional[str] = None
    if tpl.uploaded_by:
        res = await db.execute(select(User).where(User.id == tpl.uploaded_by))
        u = res.scalar_one_or_none()
        if u:
            uploader_name = u.full_name or u.username

    return TemplateInfo(
        id          = tpl.id,
        version     = tpl.version,
        filename    = tpl.filename,
        file_size   = tpl.file_size,
        file_hash   = tpl.file_hash,
        description = tpl.description,
        uploaded_by = uploader_name,
        uploaded_at = tpl.uploaded_at.isoformat() if tpl.uploaded_at else "",
        is_active   = tpl.is_active,
        source      = "database",
    )


@router.get("/admin/excel-template/download")
async def download_template(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_up),
):
    """Скачать текущий активный шаблон из БД."""
    tpl = await _get_active(db)
    if not tpl:
        raise HTTPException(404, "В БД нет активного шаблона")

    return Response(
        content      = tpl.data,
        media_type   = "application/vnd.ms-excel.sheet.macroEnabled.12",
        headers      = {
            "Content-Disposition": f'attachment; filename="{tpl.filename}"',
            "X-Template-Version": str(tpl.version),
        },
    )


@router.delete("/admin/excel-template", status_code=204)
async def delete_template(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_up),
):
    """
    Деактивировать все шаблоны в БД.
    После этого сервер вернётся к использованию WV_template.xlsm из assets.
    """
    await db.execute(
        update(ExcelTemplate).where(ExcelTemplate.is_active == True).values(is_active=False)
    )
    await db.commit()
    invalidate_base_template()
    logger.info("excel_template: all DB templates deactivated — fallback to filesystem")
