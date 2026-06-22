"""
corrections.py — API роутер для системы обучения на выборах менеджеров (Phase 2.6).

Эндпоинты:
  POST /corrections/record   — записать исправление / подтверждение менеджера
  GET  /corrections/search   — поиск в истории по тексту запроса (Pinecone)
  GET  /corrections/stats    — статистика накопленных исправлений
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_optional
from app.models.models import ManagerCorrection, Product
from app.services.embedder import embed_text, _product_text, _get_pinecone_index

logger = logging.getLogger(__name__)

router = APIRouter()

# Порог схожести для Pinecone — если выше, считаем это «точным» историческим совпадением
CORRECTION_SIMILARITY_THRESHOLD = 0.92

# Namespace в Pinecone для исправлений менеджеров
CORRECTIONS_NAMESPACE = "corrections"


# ── Pydantic схемы ────────────────────────────────────────────────────────────

class RecordCorrectionRequest(BaseModel):
    """Тело запроса для записи исправления менеджера."""
    original_name:       str
    original_article:    Optional[str] = None
    original_status:     Optional[str] = None   # not_found / ai_match / fuzzy / ...
    selected_product_id: int
    session_id:          Optional[str] = None


class CorrectionSearchResult(BaseModel):
    product_id:   int
    article:      str
    name:         str
    similarity:   float


class StatsResponse(BaseModel):
    total_corrections:   int
    pinecone_indexed:    int
    unique_products:     int


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _correction_query_text(name: str, article: Optional[str]) -> str:
    """Канонический текст для эмбеддинга исправления."""
    return _product_text(article or "", name)


async def _index_correction_in_pinecone(
    correction_id: int,
    query_text: str,
    product_id: int,
    product_article: str,
    product_name: str,
) -> bool:
    """
    Добавить вектор исправления в Pinecone namespace 'corrections'.
    ID вектора: 'corr_{correction_id}' — уникальный ключ.
    Возвращает True если успешно.
    """
    try:
        vec = await embed_text(query_text)
        index = _get_pinecone_index()
        await asyncio.to_thread(
            index.upsert,
            vectors=[{
                "id":       f"corr_{correction_id}",
                "values":   vec,
                "metadata": {
                    "product_id":  product_id,
                    "article":     product_article,
                    "name":        product_name[:200],
                    "source":      "manager_correction",
                },
            }],
            namespace=CORRECTIONS_NAMESPACE,
        )
        logger.info(
            "Correction %d indexed in Pinecone (product_id=%d, query='%s')",
            correction_id, product_id, query_text[:60],
        )
        return True
    except Exception as exc:
        logger.error("Failed to index correction %d in Pinecone: %s", correction_id, exc)
        return False


# ── Эндпоинты ─────────────────────────────────────────────────────────────────

@router.post("/record")
async def record_correction(
    body: RecordCorrectionRequest,
    db:   AsyncSession = Depends(get_db),
    user  = Depends(get_current_user_optional),
):
    """
    Записать исправление / подтверждение менеджера.

    Вызывается каждый раз когда менеджер:
    - выбирает товар для красной (not_found) строки через ArticleSearchDialog
    - подтверждает (нажимает ✓) жёлтую или ИИ-строку

    После записи в БД — сразу индексирует вектор в Pinecone (namespace "corrections"),
    чтобы следующие PDF могли использовать этот выбор как эталон.
    """
    # 1. Загружаем выбранный товар
    product = await db.get(Product, body.selected_product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    # 2. Создаём запись в БД
    correction = ManagerCorrection(
        user_id             = user.id if user else None,
        username            = user.username if user else None,
        session_id          = body.session_id,
        original_name       = body.original_name,
        original_article    = body.original_article,
        original_status     = body.original_status,
        selected_product_id = product.id,
        selected_article    = product.article,
        selected_name       = product.name,
        pinecone_indexed    = False,
    )
    db.add(correction)
    await db.commit()
    await db.refresh(correction)

    # 3. Индексируем в Pinecone (fire-and-forget с обновлением флага)
    query_text = _correction_query_text(body.original_name, body.original_article)
    if query_text.strip():
        indexed = await _index_correction_in_pinecone(
            correction_id    = correction.id,
            query_text       = query_text,
            product_id       = product.id,
            product_article  = product.article or "",
            product_name     = product.name or "",
        )
        if indexed:
            correction.pinecone_indexed = True
            await db.commit()

    return {
        "ok":            True,
        "correction_id": correction.id,
        "product_id":    product.id,
        "indexed":       correction.pinecone_indexed,
    }


@router.get("/search")
async def search_corrections(
    q:       str,
    article: Optional[str] = None,
    top_k:   int = 5,
    db:      AsyncSession = Depends(get_db),
):
    """
    Семантический поиск в истории исправлений менеджеров.
    Используется клиентом для предварительного подбора в ArticleSearchDialog.

    Возвращает до top_k наиболее похожих товаров из истории исправлений.
    """
    query_text = _correction_query_text(q, article)
    if not query_text.strip():
        return {"results": []}

    try:
        vec = await embed_text(query_text)
        index = _get_pinecone_index()
        result = await asyncio.to_thread(
            index.query,
            vector=vec,
            top_k=top_k,
            include_metadata=True,
            namespace=CORRECTIONS_NAMESPACE,
        )
    except Exception as exc:
        logger.error("Correction search failed: %s", exc)
        return {"results": []}

    results = []
    for match in result.matches:
        meta = match.metadata or {}
        if float(match.score) >= CORRECTION_SIMILARITY_THRESHOLD:
            results.append({
                "product_id": int(meta.get("product_id", 0)),
                "article":    meta.get("article", ""),
                "name":       meta.get("name", ""),
                "similarity": round(float(match.score), 3),
            })

    return {"results": results, "query": query_text}


@router.get("/stats")
async def corrections_stats(db: AsyncSession = Depends(get_db)):
    """Статистика накопленных исправлений менеджеров."""
    total = await db.scalar(select(func.count()).select_from(ManagerCorrection))
    indexed = await db.scalar(
        select(func.count()).select_from(ManagerCorrection)
        .where(ManagerCorrection.pinecone_indexed == True)
    )
    unique_products = await db.scalar(
        select(func.count(func.distinct(ManagerCorrection.selected_product_id)))
        .select_from(ManagerCorrection)
    )
    return {
        "total_corrections": total or 0,
        "pinecone_indexed":  indexed or 0,
        "unique_products":   unique_products or 0,
    }


# ── Внутренний хелпер (используется matcher_ai.py) ───────────────────────────

async def check_corrections(
    original_name:    str,
    original_article: Optional[str],
    threshold:        float = CORRECTION_SIMILARITY_THRESHOLD,
) -> Optional[int]:
    """
    Шаг 0 матчинга: проверить Pinecone namespace 'corrections'.
    Если нашли схожий запрос с similarity > threshold — вернуть product_id.
    Иначе — None (продолжить стандартный матчинг).
    """
    query_text = _correction_query_text(original_name, original_article)
    if not query_text.strip():
        return None

    try:
        vec = await embed_text(query_text)
        index = _get_pinecone_index()
        result = await asyncio.to_thread(
            index.query,
            vector=vec,
            top_k=1,
            include_metadata=True,
            namespace=CORRECTIONS_NAMESPACE,
        )
        if result.matches:
            top = result.matches[0]
            if float(top.score) >= threshold:
                meta = top.metadata or {}
                product_id = int(meta.get("product_id", 0))
                logger.info(
                    "Correction match: '%s' → product_id=%d (sim=%.3f)",
                    query_text[:60], product_id, top.score,
                )
                return product_id
    except Exception as exc:
        logger.error("check_corrections failed: %s", exc)

    return None
