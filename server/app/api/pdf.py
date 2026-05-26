import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db
from app.core.security import verify_api_key, get_current_user_optional
from app.core.audit import write_audit
from app.services.pdf_parser import parse_pdf_specification
from app.services.matcher import match_items
from app.models.models import PdfUploadLog

router = APIRouter()

MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB

# Separate thread pool for CPU-heavy PDF parsing (keeps event-loop free)
_PDF_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf_parser")


@router.post("/parse")
async def parse_pdf(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Файл должен быть в формате PDF")

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 50 МБ)")

    ip = request.client.host if request.client else None
    loop = asyncio.get_event_loop()

    # Single executor call — parse_pdf_specification now returns (items, project_name)
    # so pdfplumber opens the PDF exactly once.
    try:
        pdf_items, project_name = await loop.run_in_executor(
            _PDF_EXECUTOR, parse_pdf_specification, content
        )
    except ValueError as e:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details=str(e), ip=ip, status="error")
        raise HTTPException(422, str(e))
    except Exception as e:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details=f"parser error: {e}",
                          ip=ip, status="error")
        raise HTTPException(500, f"Ошибка при разборе PDF: {e}")

    if not pdf_items:
        await write_audit(db, current_user, "parse_pdf",
                          resource=file.filename, details="no items found",
                          ip=ip, status="error")
        raise HTTPException(404, "Позиции спецификации не найдены в PDF. Проверьте формат файла.")

    # Match items against DB
    results = await match_items(pdf_items, db)

    # Save upload history record (best-effort — never crash the response)
    try:
        log_entry = PdfUploadLog(
            user_id      = getattr(current_user, "id",        None),
            username     = getattr(current_user, "username",  None),
            full_name    = getattr(current_user, "full_name", None),
            filename     = file.filename,
            project_name = project_name or None,
            items_count  = len(results),
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

    await write_audit(db, current_user, "parse_pdf",
                      resource=file.filename,
                      details=f"items={len(results)}, project={project_name[:60] if project_name else ''}",
                      ip=ip)

    total     = len(results)
    exact     = sum(1 for r in results if r["status"] == "exact")
    multiple  = sum(1 for r in results if r["status"] == "multiple")
    fuzzy     = sum(1 for r in results if r["status"] == "fuzzy")
    not_found = sum(1 for r in results if r["status"] == "not_found")

    return {
        "filename":     file.filename,
        "project_name": project_name,
        "total":        total,
        "stats": {
            "exact":     exact,
            "multiple":  multiple,
            "fuzzy":     fuzzy,
            "not_found": not_found,
        },
        "items": results,
    }


@router.get("/history")
async def get_pdf_history(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
    current_user=Depends(get_current_user_optional),
):
    stmt = (
        select(PdfUploadLog)
        .order_by(desc(PdfUploadLog.uploaded_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id":           r.id,
            "full_name":    r.full_name or r.username or "—",
            "filename":     r.filename,
            "project_name": r.project_name or "—",
            "items_count":  r.items_count,
            "uploaded_at":  str(r.uploaded_at)[:19] if r.uploaded_at else "—",
        }
        for r in rows
    ]
