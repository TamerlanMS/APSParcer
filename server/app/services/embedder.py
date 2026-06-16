"""
embedder.py — OpenAI embeddings + Pinecone vector index for Phase 2 AI matching.

Vectorization guard conditions (both must be true, unless force=True):
  1. Today is Monday  (weekday == 0)
  2. Product DB was updated during the previous calendar week
     (at least one successful ImportLog entry Mon–Sun of last week)

This keeps API costs minimal — re-index only after a fresh DB import.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

from openai import AsyncOpenAI
from pinecone import Pinecone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.models.models import Product, ImportLog

logger = logging.getLogger(__name__)


# ── OpenAI client (lazy) ──────────────────────────────────────────────────────

_oai_client: Optional[AsyncOpenAI] = None


def _get_oai_client() -> AsyncOpenAI:
    global _oai_client
    if _oai_client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env or docker-compose."
            )
        _oai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    return _oai_client


# ── Pinecone client (lazy) ────────────────────────────────────────────────────

_pinecone_index = None


def _get_pinecone_index():
    """Return the Pinecone Index object (created once, reused across calls)."""
    global _pinecone_index
    if _pinecone_index is None:
        if not settings.PINECONE_API_KEY:
            raise RuntimeError(
                "PINECONE_API_KEY is not set. Add it to .env or docker-compose."
            )
        if not settings.PINECONE_HOST:
            raise RuntimeError(
                "PINECONE_HOST is not set. Add it to .env or docker-compose. "
                "Find it in console.pinecone.io → your index → host URL."
            )
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        # Use host= for direct connection (faster, no control-plane lookup)
        _pinecone_index = pc.Index(host=settings.PINECONE_HOST)
    return _pinecone_index


# ── Text helpers ──────────────────────────────────────────────────────────────

def _product_text(article: str, name: str) -> str:
    """Canonical embedding text: 'ARTICLE | Name of product'."""
    parts = [p.strip() for p in [article, name] if p and p.strip()]
    return " | ".join(parts)


# ── Single embed with in-process LRU cache ────────────────────────────────────

_embed_cache: dict[str, List[float]] = {}
_CACHE_MAX = 4096   # entries — cleared wholesale on overflow (simple eviction)


async def embed_text(text: str) -> List[float]:
    """
    Embed a single string → 1536-dim vector (text-embedding-3-small).
    Results are cached in-process to avoid duplicate API calls within a session.
    """
    if not text.strip():
        raise ValueError("Cannot embed empty text")

    key = text.strip().lower()
    if key in _embed_cache:
        return _embed_cache[key]

    client = _get_oai_client()
    resp = await client.embeddings.create(
        model=settings.OPENAI_EMBED_MODEL,
        input=[key],
    )
    vec = resp.data[0].embedding

    if len(_embed_cache) >= _CACHE_MAX:
        _embed_cache.clear()
    _embed_cache[key] = vec
    return vec


# ── Vectorization guards ─────────────────────────────────────────────────────

def _is_monday() -> bool:
    """True only on Mondays (weekday index 0)."""
    return datetime.now().weekday() == 0


async def _db_imported_last_week(session_factory: async_sessionmaker) -> bool:
    """
    Returns True if at least one successful product import was made
    through the application during the previous calendar week (Mon–Sun).

    Uses ImportLog — populated only by the /database/import/products endpoint,
    so this strictly tracks imports done via the app, not manual DB changes.

    Called on Mondays, so "last week" = today−7 days .. today−1 day.
    """
    today       = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = today - timedelta(days=7)
    last_sunday = today - timedelta(days=1)

    async with session_factory() as session:
        result = await session.execute(
            select(func.count(ImportLog.id)).where(
                ImportLog.created_at >= last_monday,
                ImportLog.created_at <= last_sunday,
                ImportLog.status == "success",
            )
        )
        count = result.scalar() or 0

    logger.info(
        "embed guard: found %d successful app import(s) between %s and %s",
        count,
        last_monday.strftime("%Y-%m-%d"),
        last_sunday.strftime("%Y-%m-%d"),
    )
    return count > 0


# ── Batch embed + Pinecone upsert ─────────────────────────────────────────────

_BATCH_SIZE    = 512   # OpenAI embeddings.create — conservative (max 2048)
_PC_BATCH_SIZE = 100   # Pinecone recommended upsert batch size


async def embed_products_batch(
    session_factory: async_sessionmaker,
    limit: int = 0,
    force: bool = False,
) -> int:
    """
    Embed all active products via OpenAI and upsert into Pinecone.

    Guards (both must be true; skipped when force=True):
      1. Today is Monday — vectorization runs once a week at the start of the week.
      2. Product DB was imported via the app during the previous Mon–Sun
         (checked via ImportLog). If no import happened last week,
         re-indexing is pointless — skip it.

    Each vector in Pinecone:
      id       = str(product.id)
      values   = 1536-dim float list
      metadata = {product_id, article, name, brand, unit}

    Returns the number of products upserted (0 if guarded or no products).
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping vectorization")
        return 0
    if not settings.PINECONE_API_KEY or not settings.PINECONE_HOST:
        logger.warning("PINECONE_API_KEY or PINECONE_HOST not set — skipping vectorization")
        return 0

    if not force:
        if not _is_monday():
            logger.info(
                "embed_products_batch: today is %s, not Monday — skipping",
                datetime.now().strftime("%A"),
            )
            return 0

        if not await _db_imported_last_week(session_factory):
            logger.info(
                "embed_products_batch: no product import via app last week — skipping vectorization"
            )
            return 0

    logger.info("embed_products_batch: guards passed — starting full vectorization")

    oai    = _get_oai_client()
    index  = _get_pinecone_index()

    # Load all active products
    async with session_factory() as session:
        stmt = select(Product).where(Product.is_active == True)
        if limit:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        products: Sequence[Product] = result.scalars().all()

    if not products:
        logger.info("embed_products_batch: no active products found")
        return 0

    logger.info("embed_products_batch: %d products to embed → Pinecone", len(products))
    upserted = 0

    for batch_start in range(0, len(products), _BATCH_SIZE):
        batch = products[batch_start: batch_start + _BATCH_SIZE]
        texts = [_product_text(p.article or "", p.name or "") for p in batch]

        # ── OpenAI embedding ──────────────────────────────────────────────────
        try:
            resp = await oai.embeddings.create(
                model=settings.OPENAI_EMBED_MODEL,
                input=texts,
            )
        except Exception as exc:
            logger.error("OpenAI embedding batch [%d] failed: %s", batch_start, exc)
            break

        vectors = [item.embedding for item in resp.data]

        # ── Pinecone upsert (sync → run in thread) ────────────────────────────
        pc_records = [
            {
                "id":     str(p.id),
                "values": vec,
                "metadata": {
                    "product_id": p.id,
                    "article":    (p.article or "").strip(),
                    "name":       (p.name    or "").strip(),
                    "brand":      (p.brand   or "").strip(),
                    "unit":       (p.unit    or "шт.").strip(),
                },
            }
            for p, vec in zip(batch, vectors)
        ]

        for pc_start in range(0, len(pc_records), _PC_BATCH_SIZE):
            pc_chunk = pc_records[pc_start: pc_start + _PC_BATCH_SIZE]
            await asyncio.to_thread(index.upsert, vectors=pc_chunk)

        upserted += len(batch)
        logger.info(
            "embed_products_batch: %d / %d upserted",
            min(batch_start + _BATCH_SIZE, len(products)),
            len(products),
        )
        # Small pause to respect OpenAI rate limits
        await asyncio.sleep(0.2)

    logger.info("embed_products_batch: done — %d products in Pinecone index", upserted)
    return upserted
