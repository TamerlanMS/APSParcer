"""
Загрузка и подбор по спецификации в формате Excel.

Отличие от PDF-ветки: исходник уже структурирован, распознавать текст не нужно —
файл разбирается парсером spec_parser, затем позиции прогоняются через тот же
matcher, что и для PDF. Ответ совместим с форматом /pdf/parse-stream, поэтому
страница предпросмотра работает с ним без изменений.

Дополнительно каждая позиция несёт `row` и `sheet` — координаты в исходном
файле, чтобы потом записать подбор обратно в ту же строку.
"""
import asyncio
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter, UploadFile, File, Depends, HTTPException, Request, Query,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key, get_current_user_optional
from app.core.audit import write_audit
from app.services.spec_parser import parse_spec_excel, get_sheet_names
from app.services.matcher import match_items

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_SPEC_SIZE = 50 * 1024 * 1024        # 50 MB
ALLOWED_EXT   = (".xlsx", ".xlsm", ".xls")
_SPEC_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="spec_parser")

# gen — общая база позиций прейскуранта АГСК: без бренда и артикула,
# но с ценой КазНИИСА. Участвует в подборе наравне с остальными.
ALL_SEGMENTS = ["ss", "os", "sil", "gen"]


def _parse_segments(raw: Optional[str]) -> List[str]:
    if not raw or raw.strip().lower() == "all":
        return ALL_SEGMENTS
    segs = [s.strip().lower() for s in raw.split(",") if s.strip()]
    valid = [s for s in segs if s in ALL_SEGMENTS]
    return valid if valid else ["ss"]


def _build_result(filename: str, project_name: str,
                  results: List[Dict], source_path: str = "") -> Dict:
    total     = sum(1 for r in results if r.get("status") != "heading")
    exact     = sum(1 for r in results if r.get("status") == "exact")
    multiple  = sum(1 for r in results if r.get("status") == "multiple")
    fuzzy     = sum(1 for r in results if r.get("status") == "fuzzy")
    not_found = sum(1 for r in results if r.get("status") == "not_found")
    return {
        "filename":     filename,
        "project_name": project_name,
        "source_kind":  "spec",          # признак режима подбора для клиента
        "source_path":  source_path,     # путь исходного файла на машине менеджера
        "ai_mode":      False,
        "total":        total,
        "stats": {
            "exact":     exact,
            "multiple":  multiple,
            "fuzzy":     fuzzy,
            "ai_match":  0,
            "not_found": not_found,
        },
        "items": results,
    }


def _merge_spec_fields(results: List[Dict], spec_items: List[Dict]) -> List[Dict]:
    """Возвращает в результат служебные поля спецификации.

    matcher отдаёт только свой набор ключей, поэтому координаты строки и
    сведения об иерархии переносим из исходных позиций по порядку.
    """
    for res, src in zip(results, spec_items):
        res["row"]          = src.get("row")
        res["sheet"]        = src.get("sheet")
        # Исходный текст наименования (до снятия меток «На вводе:» и т.п.)
        res["name_orig"]    = src.get("name_orig", src.get("name_raw", ""))
        res["brand_raw"]    = src.get("brand_raw", "")
        res["note_raw"]     = src.get("note_raw", "")
        res["is_component"] = src.get("is_component", False)
        res["parent_pos"]   = src.get("parent_pos", "")
        if src.get("is_heading"):
            res["is_heading"] = True
    return results


@router.get("/sheets")
async def spec_sheets(
    file: UploadFile = File(...),
    _key: str = Depends(verify_api_key),
):
    """Список листов файла — если спецификация не на первом листе."""
    if not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Файл должен быть .xlsx / .xlsm / .xls")
    content = await file.read()
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(tmp_fd)
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(content)
        return {"sheets": get_sheet_names(tmp_path)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/parse-stream")
async def parse_spec_stream(
    request: Request,
    file: UploadFile = File(...),
    sheet: Optional[str] = Query(None, description="Имя листа со спецификацией"),
    source_path: Optional[str] = Query(None, description="Путь файла у менеджера"),
    segments: Optional[str] = Query(
        default="ss", description="Сегменты поиска: 'ss', 'os', 'sil', 'ss,os', 'all'",
    ),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Разбор спецификации Excel с автоподбором. Прогресс отдаётся через SSE."""
    fname = file.filename or "spec.xlsx"
    if not fname.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Файл должен быть .xlsx / .xlsm / .xls")

    content = await file.read()
    if len(content) > MAX_SPEC_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 50 МБ)")

    ip       = request.client.host if request.client else None
    loop     = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    seg_list = _parse_segments(segments)

    def _progress(pct: int, stage: str, msg: str) -> None:
        payload = json.dumps({"pct": pct, "stage": stage, "msg": msg},
                             ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def _process() -> None:
        tmp_path = ""
        try:
            _progress(5, "upload", "Файл получен, читаем спецификацию...")

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(fname)[1] or ".xlsx")
            os.close(tmp_fd)
            with open(tmp_path, "wb") as fh:
                fh.write(content)

            _progress(20, "parse", "Разбор структуры спецификации...")
            spec_items = await loop.run_in_executor(
                _SPEC_EXECUTOR, parse_spec_excel, tmp_path, sheet
            )
            logger.info("spec parse: %s → %d элементов", fname, len(spec_items))

            if not spec_items:
                await write_audit(db, current_user, "parse_spec",
                                  resource=fname, details="no items",
                                  ip=ip, status="error")
                await queue.put(json.dumps(
                    {"error": "В файле не найдено позиций спецификации. "
                              "Проверьте, что есть строка заголовка с колонками "
                              "«Наименование», «Тип/марка», «Количество»."},
                    ensure_ascii=False,
                ))
                return

            real = sum(1 for i in spec_items if not i.get("is_heading"))
            _progress(45, "match", f"Подбор {real} позиций в базе данных...")
            try:
                results = await asyncio.wait_for(
                    match_items(spec_items, db, segments=seg_list), timeout=600
                )
            except asyncio.TimeoutError:
                await queue.put(json.dumps(
                    {"error": f"Подбор завис после 10 минут ({real} позиций)."},
                    ensure_ascii=False,
                ))
                return

            results = _merge_spec_fields(results, spec_items)

            project_name = os.path.splitext(fname)[0].strip()
            await write_audit(db, current_user, "parse_spec",
                              resource=fname,
                              details=f"items={len(results)}, sheet={sheet or 'первый'}",
                              ip=ip)

            _progress(98, "done", "Готово!")
            await queue.put(json.dumps(
                {"done": True,
                 "result": _build_result(fname, project_name, results,
                                         source_path or "")},
                ensure_ascii=False,
            ))

        except ValueError as exc:
            await write_audit(db, current_user, "parse_spec", resource=fname,
                              details=str(exc), ip=ip, status="error")
            await queue.put(json.dumps({"error": str(exc)}, ensure_ascii=False))
        except Exception as exc:
            logger.exception("spec parse failed: %s", exc)
            await write_audit(db, current_user, "parse_spec", resource=fname,
                              details=f"stream error: {exc}", ip=ip, status="error")
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
