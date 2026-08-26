"""
Приём сметного документа генподрядчика и сопоставление с позициями проекта.

Клиент присылает файл сметы и текущий список позиций предпросмотра,
в ответ получает те же позиции с проставленной сметной ценой.
Позиции, которым цену подобрать не удалось, менеджер заполняет вручную.
"""
import asyncio
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Form

from app.core.security import verify_api_key, get_current_user_optional
from app.services.estimate_parser import parse_estimate_excel, match_estimate

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_ESTIMATE_SIZE = 50 * 1024 * 1024        # 50 МБ
ALLOWED_EXT = (".xlsx", ".xlsm", ".xls")
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="estimate")


@router.post("/parse")
async def parse_estimate(
    request: Request,
    file: UploadFile = File(...),
    items: str = Form("[]", description="JSON-массив позиций предпросмотра"),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Разбирает смету и проставляет сметные цены переданным позициям.

    items — список позиций со страницы предпросмотра в виде JSON.
    Если он пуст, вернутся только разобранные строки сметы.
    """
    fname = file.filename or "estimate.xlsx"
    if not fname.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Смета должна быть в формате .xlsx / .xlsm / .xls")

    content = await file.read()
    if len(content) > MAX_ESTIMATE_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 50 МБ)")

    try:
        preview_items: List[Dict[str, Any]] = json.loads(items or "[]")
        if not isinstance(preview_items, list):
            preview_items = []
    except json.JSONDecodeError:
        raise HTTPException(400, "Поле items должно быть корректным JSON-массивом")

    ip = request.client.host if request.client else None
    tmp_path = ""
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=os.path.splitext(fname)[1] or ".xlsx")
        os.close(tmp_fd)
        with open(tmp_path, "wb") as fh:
            fh.write(content)

        # Разбор блокирующий (openpyxl) — уводим в поток
        loop = asyncio.get_running_loop()
        parsed = await loop.run_in_executor(_EXECUTOR, parse_estimate_excel, tmp_path)

        if not parsed["items"]:
            raise HTTPException(
                400,
                "В смете не найдено позиций. Проверьте, что в файле есть листы "
                "с метками Q9, G9, K9 или РС и таблица с колонками "
                "«Наименование», «Количество», «Стоимость единицы измерения».",
            )

        match_stats = {}
        if preview_items:
            match_stats = match_estimate(preview_items, parsed["items"])

        logger.info("estimate: %s — листов %d, позиций %d, сопоставлено %d",
                    fname, parsed["stats"]["sheets_used"],
                    parsed["stats"]["items"],
                    match_stats.get("total", 0) - match_stats.get("unmatched", 0))

        return {
            "filename":       fname,
            "sheets":         parsed["sheets"],
            "skipped_sheets": parsed["skipped_sheets"],
            "stats":          parsed["stats"],
            "match":          match_stats,
            "items":          preview_items,
            "estimate_items": parsed["items"],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("estimate parse failed: %s", exc)
        raise HTTPException(500, f"Ошибка разбора сметы: {exc}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
