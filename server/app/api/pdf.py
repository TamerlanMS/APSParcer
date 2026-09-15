import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
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
from app.services.tech_params import extract_tech_params
from app.models.models import PdfUploadLog

logger = logging.getLogger(__name__)


class RematchRequest(BaseModel):
    items: List[Dict[str, Any]]


router = APIRouter()

MAX_PDF_SIZE       = 200 * 1024 * 1024  # 200 MB — single file (scan) limit
MAX_PDF_SIZE_MULTI =  20 * 1024 * 1024  # 20 MB per file when multiple files sent
_PDF_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pdf_parser")


# gen — общая база позиций прейскуранта АГСК: без бренда и артикула,
# но с ценой КазНИИСА. Участвует в подборе наравне с остальными.
ALL_SEGMENTS = ["ss", "os", "sil", "gen"]


def _parse_segments(raw: Optional[str]) -> List[str]:
    """Разбирает строку "ss,os" или "all" в список валидных сегментов."""
    if not raw or raw.strip().lower() == "all":
        return ALL_SEGMENTS
    segs = [s.strip().lower() for s in raw.split(",") if s.strip()]
    valid = [s for s in segs if s in ALL_SEGMENTS]
    return valid if valid else ["ss"]


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_result(filename, project_name, ai_mode_used, results):
    total     = sum(1 for r in results if r.get("status") != "heading")
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
    segments: Optional[str] = Query(
        default="ss",
        description="Сегменты для поиска: 'ss', 'os', 'sil', 'ss,os', 'all'",
    ),
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
    seg_list = _parse_segments(segments)

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

            # Extract tech params with AI (Phase 2.2) — only when AI mode is on
            if use_ai and settings.OPENAI_API_KEY:
                _progress(72, "tech_params", "Извлечение технических параметров...")
                try:
                    await extract_tech_params(pdf_items)
                    tp_count = sum(1 for it in pdf_items if it.get("tech_params"))
                    logger.info("Tech params extracted: %d/%d items", tp_count, len(pdf_items))
                except Exception as _tp_exc:
                    logger.warning("extract_tech_params failed (non-fatal): %s", _tp_exc)

            _progress(75, "match", f"Подбор {len(pdf_items)} позиций в базе данных...")
            logger.info("Matching phase: %d pdf_items, use_ai=%s", len(pdf_items), use_ai)
            try:
                if use_ai:
                    results = await asyncio.wait_for(
                        match_items_ai(pdf_items, db, segments=seg_list), timeout=600
                    )
                else:
                    results = await asyncio.wait_for(
                        match_items(pdf_items, db, segments=seg_list), timeout=600
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



# ── Multi-file SSE streaming parse endpoint ───────────────────────────────────

@router.post("/parse-multi-stream")
async def parse_pdf_multi_stream(
    request: Request,
    files: List[UploadFile] = File(...),
    ai_mode: bool = Query(False, description="Use AI semantic matching"),
    segments: Optional[str] = Query(
        default="ss",
        description="Segments: ss, os, sil, ss,os, all",
    ),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    """Parse multiple PDFs in parallel, stream all progress via SSE.

    Progress events: {"file_idx": i, "filename": "...", "pct": N, "stage": "...", "msg": "..."}
    File done:       {"file_idx": i, "filename": "...", "file_done": True, "result": {...}}
    File error:      {"file_idx": i, "filename": "...", "file_error": "..."}
    All done:        {"all_done": True, "results": [...]}
    """
    if not files:
        raise HTTPException(400, "No files provided")

    ip = request.client.host if request.client else None
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    use_ai = ai_mode and bool(settings.OPENAI_API_KEY)
    seg_list = _parse_segments(segments)
    logger.info("parse-multi-stream: segments_raw=%r → seg_list=%s, files=%d",
                segments, seg_list, len(files))

    # Read all files into memory before streaming starts
    # Size rules: single file → up to 200 MB (may be a large scan);
    #             multiple files → each must be ≤ 20 MB.
    is_multi = len(files) > 1
    size_limit = MAX_PDF_SIZE_MULTI if is_multi else MAX_PDF_SIZE
    size_limit_mb = size_limit // (1024 * 1024)
    file_data: List[tuple] = []
    for i, uf in enumerate(files):
        if not uf.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"File {uf.filename} must be PDF")
        content = await uf.read()
        if len(content) > size_limit:
            raise HTTPException(
                413,
                f"File {uf.filename} too large ({len(content) // (1024*1024)} MB). "
                f"{'Multiple files: max ' + str(size_limit_mb) + ' MB each. For larger files upload one at a time.' if is_multi else 'Max ' + str(size_limit_mb) + ' MB.'}",
            )
        file_data.append((i, uf.filename, content))

    n_files = len(file_data)
    results_store: dict = {}

    async def _process_one(idx: int, fname: str, content: bytes) -> None:
        import os as _os

        def _push(payload: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        def _progress(pct: int, stage: str, msg: str) -> None:
            _push(json.dumps(
                {"file_idx": idx, "filename": fname, "pct": pct, "stage": stage, "msg": msg},
                ensure_ascii=False,
            ))

        try:
            _progress(5, "upload", f"Обработка {fname}...")
            logger.info("Multi-PDF parse START [%d/%d]: %s (%d bytes)",
                        idx + 1, n_files, fname, len(content))

            pdf_items, project_name = await loop.run_in_executor(
                _PDF_EXECUTOR, parse_pdf_specification, content, _progress
            )

            if not project_name:
                project_name = _os.path.splitext(fname)[0].strip()

            if not pdf_items:
                _push(json.dumps(
                    {"file_idx": idx, "filename": fname,
                     "file_error": f"Спецификация не найдена в файле {fname}"},
                    ensure_ascii=False,
                ))
                results_store[idx] = None
                return

            if use_ai and settings.OPENAI_API_KEY:
                _progress(72, "tech_params", f"{fname}: параметры...")
                try:
                    await extract_tech_params(pdf_items)
                except Exception as _e:
                    logger.warning("extract_tech_params [%s]: %s", fname, _e)

            _n_items = sum(1 for i in pdf_items if not i.get("is_heading", False))
            _progress(75, "match", f"{fname}: подбор {_n_items} поз...")
            try:
                if use_ai:
                    matched = await asyncio.wait_for(
                        match_items_ai(pdf_items, db, segments=seg_list), timeout=600
                    )
                else:
                    matched = await asyncio.wait_for(
                        match_items(pdf_items, db, segments=seg_list), timeout=600
                    )
            except asyncio.TimeoutError:
                _push(json.dumps(
                    {"file_idx": idx, "filename": fname,
                     "file_error": f"Подбор завис (> 10 мин) для {fname}"},
                    ensure_ascii=False,
                ))
                results_store[idx] = None
                return

            await _log_upload(db, current_user, fname, project_name, matched)
            await write_audit(db, current_user, "parse_pdf",
                              resource=fname,
                              details=f"items={len(matched)}, project={project_name[:60]}",
                              ip=ip)

            _n_matched = sum(1 for i in matched if i.get("status") != "heading")
            _progress(100, "done", f"{fname}: готово! {_n_matched} позиций")
            result = _build_result(fname, project_name, use_ai, matched)
            results_store[idx] = result

            _push(json.dumps(
                {"file_idx": idx, "filename": fname, "file_done": True, "result": result},
                ensure_ascii=False,
            ))
            logger.info("Multi-PDF parse DONE [%d/%d]: %s — %d items",
                        idx + 1, n_files, fname, len(matched))

        except Exception as exc:
            logger.exception("Multi-PDF parse ERROR [%d/%d]: %s", idx + 1, n_files, fname)
            loop.call_soon_threadsafe(queue.put_nowait, json.dumps(
                {"file_idx": idx, "filename": fname, "file_error": str(exc)},
                ensure_ascii=False,
            ))
            results_store[idx] = None

    async def _run_all() -> None:
        await asyncio.gather(*[
            _process_one(i, fname, content)
            for i, fname, content in file_data
        ])
        final = [results_store[i] for i in range(n_files) if results_store.get(i) is not None]
        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(
            {"all_done": True, "results": final}, ensure_ascii=False,
        ))

    asyncio.create_task(_run_all())

    async def _events():
        while True:
            data = await queue.get()
            yield "data: " + data + "\n\n"
            ev = json.loads(data)
            if "all_done" in ev or "all_error" in ev:
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
    segments: Optional[str] = Query(
        default="ss",
        description="Сегменты для поиска: 'ss', 'os', 'sil', 'ss,os', 'all'",
    ),
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
    seg_list = _parse_segments(segments)
    if use_ai:
        results = await match_items_ai(pdf_items, db, segments=seg_list)
    else:
        results = await match_items(pdf_items, db, segments=seg_list)

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
