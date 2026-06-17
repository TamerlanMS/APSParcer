import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db
from app.core.config import settings
from app.core.security import verify_api_key, get_current_user_optional
from app.core.audit import write_audit
from app.services.pdf_parser import parse_pdf_specification
from app.services.matcher import match_items
from app.services.matcher_ai import match_items_ai
from app.models.models import PdfUploadLog

logger = logging.getLogger(__name__)


class RematchRequest(BaseModel):
    items: List[Dict[str, Any]]


router = APIRouter()

MAX_PDF_SIZE = 200 * 1024 * 1024  # 200 MB
_PDF_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pdf_parser")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_result(filename, project_name, ai_mode_used, results):
    total     = len(results)
    exact     = sum(1 for r in results if r["status"] == "exact")
    multiple  = sum(1 for r in results if r["status"] == "multiple")
    fuzzy     = sum(1 for r in results if r["status"] == "fuzzy")
    ai_match  = sum(1 for r in results if r["status"] == "ai_match")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    return {
        "filename":     filename,
        "project_name": project_name,
        "ai_mode":      ai_mode_used,
        "total":        total,
        "stats": {
            "exact":     exact,
            "multiple":  multiple,
            "fuzzy":     fuzzy,
            "ai_match":  ai_match,
            "not_found": not_found,
        },
        "items": results,
    }


async def _log_upload(db, current_user, filename, project_name, results):
    try:
        entry = PdfUploadLog(
            user_id      = getattr(current_user, "id",        None),
            username     = getattr(current_user, "username",  None),
            full_name    = getattr(current_user, "full_name", None),
            filename     = filename,
            project_name = project_name or None,
            items_count  = len(results),
        )
        db.add(entry)
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass


# ── SSE streaming parse endpoint ──────────────────────────────────────────────

@router.post("/parse-stream")
async def parse_pdf_stream(
    request: Request,
    file: UploadFile = File(...),
    ai_mode: bool = Query(False, description="Use AI semantic matching"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Parse PDF and stream progress via SSE.

    Each event: data: {pct, stage, msg}
    Final:      data: {done: true, result: {...}}
    Error:      data: {error: "..."}
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be PDF")

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(413, "File too large (max 200 MB)")

    ip = request.client.host if request.client else None
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    fname = file.filename
    use_ai = ai_mode and bool(settings.OPENAI_API_KEY)

    def _progress(pct: int, stage: str, msg: str) -> None:
        payload = json.dumps({"pct": pct, "stage": stage, "msg": msg}, ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def _process() -> None:
        try:
            _progress(5, "upload", "Файл получен, запускаем обработку...")

            logger.info("PDF parse START: %s (%d bytes)", fname, len(content))
            pdf_items, project_name = await loop.run_in_executor(
                _PDF_EXECUTOR, parse_pdf_specification, content, _progress
            )
            logger.info("PDF parse DONE: %d items, project=%r",
                        len(pdf_items), (project_name or "")[:60])

            # Fallback: если парсер не нашёл имя проекта — берём имя файла без расширения
            if not project_name:
                import os as _os
                project_name = _os.path.splitext(fname)[0].strip()
                logger.info("project_name fallback → filename: %r", project_name)

            if not pdf_items:
                await write_audit(db, current_user, "parse_pdf",
                                  resource=fname, details="no items found",
                                  ip=ip, status="error")
                await queue.put(json.dumps(
                    {"error": "No spec items found in PDF. Check file format."},
                    ensure_ascii=False,
                ))
                return

            _progress(75, "match", f"Подбор {len(pdf_items)} позиций в базе данных...")
            logger.info("Matching phase: %d pdf_items, use_ai=%s", len(pdf_items), use_ai)
            try:
                if use_ai:
                    results = await asyncio.wait_for(
                        match_items_ai(pdf_items, db), timeout=600
                    )
                else:
                    results = await asyncio.wait_for(
                        match_items(pdf_items, db), timeout=600
                    )
            except asyncio.TimeoutError:
                logger.error("Matching timed out after 600s for %d items", len(pdf_items))
                await queue.put(json.dumps(
                    {"error": f"Подбор позиций завис после 10 минут ({len(pdf_items)} позиций). Попробуйте повторить."},
                    ensure_ascii=False,
                ))
                return
            logger.info("Matching phase done: %d results", len(results))

            _progress(92, "save", "Сохранение результатов...")
            await _log_upload(db, current_user, fname, project_name, results)

            snip = project_name[:60] if project_name else ""
            await write_audit(db, current_user, "parse_pdf",
                              resource=fname,
                              details=f"items={len(results)}, project={snip}",
                              ip=ip)

            _progress(98, "done", "Готово!")
            payload = json.dumps(
                {"done": True, "result": _build_result(fname, project_name, use_ai, results)},
                ensure_ascii=False,
            )
            await queue.put(payload)

        except ValueError as exc:
            await write_audit(db, current_user, "parse_pdf",
                              resource=fname, details=str(exc),
                              ip=ip, status="error")
            await queue.put(json.dumps({"error": str(exc)}, ensure_ascii=False))
        except Exception as exc:
            await write_audit(db, current_user, "parse_pdf",
                              resource=fname, details=f"stream error: {exc}",
                              ip=ip, status="error")
            await queue.put(json.dumps({"error": f"Ошибка: {exc}"}, ensure_ascii=False))

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


# ── Classic parse (non-streaming) ────────────────────────────────────────────

@router.post("/parse")
async def parse_pdf(
    request: Request,
    file: UploadFile = File(...),
    ai_mode: bool = Query(False, description="Use AI semantic matching (Phase 2)"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be PDF")

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(413, "File too large (max 200 MB)")

    ip = request.client.host if request.client else None
    loop = asyncio.get_event_loop()

    try:
        pdf_items, project_name = await loop.run_in_executor(
            _PDF_EXECUTOR, parse_pdf_specification, content, None
        )
    except ValueError as e:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details=str(e), ip=ip, status="error")
        raise HTTPException(422, str(e))
    except Exception as e:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details=f"parser error: {e}",
                          ip=ip, status="error")
        raise HTTPException(500, f"PDF parse error: {e}")

    if not pdf_items:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details="no items found",
                          ip=ip, status="error")
        raise HTTPException(404, "No spec items found in PDF. Check file format.")

    use_ai = ai_mode and bool(settings.OPENAI_API_KEY)
    if use_ai:
        results = await match_items_ai(pdf_items, db)
    else:
        results = await match_items(pdf_items, db)

    await _log_upload(db, current_user, file.filename, project_name, results)

    snip = project_name[:60] if project_name else ""
    await write_audit(db, current_user, "parse_pdf",
                      resource=file.filename,
                      details=f"items={len(results)}, project={snip}",
                      ip=ip)

    return _build_result(file.filename, project_name, use_ai, results)


# ── Rematch ──────────────────────────────────────────────────────────────────

@router.post("/rematch")
async def rematch_items(
    body: RematchRequest,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Re-match a list of items via AI matcher."""
    if not body.items:
        return {"items": [], "total": 0}
    results = await match_items_ai(body.items, db)
    return {"items": results, "total": len(results)}


# ── History ──────────────────────────────────────────────────────────────────

@router.get("/history")
async def get_pdf_history(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    stmt = select(PdfUploadLog).order_by(desc(PdfUploadLog.uploaded_at)).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id":           r.id,
            "full_name":    r.full_name or r.username or "---",
            "filename":     r.filename,
            "project_name": r.project_name or "---",
            "items_count":  r.items_count,
            "uploaded_at":  str(r.uploaded_at)[:19] if r.uploaded_at else "---",
        }
        for r in rows
    ]
