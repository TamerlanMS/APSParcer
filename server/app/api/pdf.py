from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import verify_api_key
from app.services.pdf_parser import parse_pdf_specification
from app.services.matcher import match_items

router = APIRouter()

MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/parse")
async def parse_pdf(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """
    Принимает PDF, парсит спецификацию, ищет в БД.
    Возвращает JSON с позициями и кандидатами для каждой.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Файл должен быть в формате PDF")

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(413, "Файл слишком большой (максимум 50 МБ)")

    # Парсинг PDF
    try:
        pdf_items = parse_pdf_specification(content)
    except ValueError as e:
        raise HTTPException(422, str(e))

    if not pdf_items:
        raise HTTPException(404, "Позиции спецификации не найдены в PDF. Проверьте формат файла.")

    # Поиск в БД
    results = await match_items(pdf_items, db)

    # Статистика
    total = len(results)
    exact = sum(1 for r in results if r["status"] == "exact")
    multiple = sum(1 for r in results if r["status"] == "multiple")
    fuzzy = sum(1 for r in results if r["status"] == "fuzzy")
    not_found = sum(1 for r in results if r["status"] == "not_found")

    return {
        "filename": file.filename,
        "total": total,
        "stats": {
            "exact": exact,
            "multiple": multiple,
            "fuzzy": fuzzy,
            "not_found": not_found,
        },
        "items": results,
    }
