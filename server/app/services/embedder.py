"""
embedder.py — OpenAI embeddings + Pinecone vector index for Phase 2 AI matching.

Vectorization guard conditions (both must be true, unless force=True):
  1. Today matches the segment's assigned weekday
  2. Product DB was updated during the previous calendar week
     (at least one successful ImportLog entry for that segment Mon–Sun of last week)

Pinecone namespace mapping:
  ss  → "products_ss"   (Слаботочные системы)  — vectorizes on Monday (0)
  os  → "products_os"   (Осветительные системы) — vectorizes on Wednesday (2)
  sil → "products_sil"  (Силовые системы)        — vectorizes on Friday (4)
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

# ── Segment → Pinecone namespace + vectorization weekday ─────────────────────
SEGMENT_NAMESPACE = {
    "ss":  "products_ss",   # Monday
    "os":  "products_os",   # Wednesday
    "sil": "products_sil",  # Friday
}
SEGMENT_WEEKDAY = {
    "ss":  0,   # Monday
    "os":  2,   # Wednesday
    "sil": 4,   # Friday
}


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


async def embed_texts_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Embed a list of strings in a single OpenAI API call (much faster than N × embed_text).

    Returns a list of vectors in the same order as `texts`.
    Items that are empty or fail will be None in the result.
    Hits the in-process cache first; only uncached texts go to the API.
    """
    if not texts:
        return []

    result: List[Optional[List[float]]] = [None] * len(texts)
    keys   = [t.strip().lower() for t in texts]

    # Fill from cache
    uncached_idxs: List[int] = []
    for i, key in enumerate(keys):
        if not key:
            continue  # empty string → stays None
        if key in _embed_cache:
            result[i] = _embed_cache[key]
        else:
            uncached_idxs.append(i)

    if not uncached_idxs:
        return result

    # Single API call for all uncached texts
    client = _get_oai_client()
    batch_inputs = [keys[i] for i in uncached_idxs]
    try:
        resp = await client.embeddings.create(
            model=settings.OPENAI_EMBED_MODEL,
            input=batch_inputs,
        )
        if len(_embed_cache) >= _CACHE_MAX:
            _embed_cache.clear()
        for local_idx, api_item in enumerate(resp.data):
            global_idx = uncached_idxs[local_idx]
            vec = api_item.embedding
            _embed_cache[keys[global_idx]] = vec
            result[global_idx] = vec
    except Exception as exc:
        logger.error("embed_texts_batch API call failed: %s", exc)
        # leave uncached entries as None

    return result


# ── Vectorization guards ─────────────────────────────────────────────────────

def _is_segment_day(segment: str) -> bool:
    """True only on the segment's assigned weekday."""
    expected = SEGMENT_WEEKDAY.get(segment, 0)
    return datetime.now().weekday() == expected


async def _db_imported_last_week(
    session_factory: async_sessionmaker,
    segment: str = "ss",
) -> bool:
    """
    Returns True if at least one successful product import was made for this segment
    during the previous calendar week (Mon–Sun).
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
                ImportLog.segment == segment,
            )
        )
        count = result.scalar() or 0

    logger.info(
        "embed guard [%s]: found %d successful import(s) between %s and %s",
        segment,
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
    segment: str = "ss",
    limit: int = 0,
    force: bool = False,
) -> int:
    """
    Embed all active products of a given segment via OpenAI and upsert into Pinecone.

    Uses namespace SEGMENT_NAMESPACE[segment] within the single Pinecone index.

    Guards (both must be true; skipped when force=True):
      1. Today matches the segment's assigned weekday.
      2. Product DB for this segment was imported via the app during the previous Mon–Sun.

    Returns the number of products upserted (0 if guarded or no products).
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping vectorization")
        return 0
    if not settings.PINECONE_API_KEY or not settings.PINECONE_HOST:
        logger.warning("PINECONE_API_KEY or PINECONE_HOST not set — skipping vectorization")
        return 0

    namespace = SEGMENT_NAMESPACE.get(segment, f"products_{segment}")

    if not force:
        if not _is_segment_day(segment):
            logger.info(
                "embed_products_batch [%s]: today is %s, not the assigned day — skipping",
                segment, datetime.now().strftime("%A"),
            )
            return 0

        if not await _db_imported_last_week(session_factory, segment):
            logger.info(
                "embed_products_batch [%s]: no import last week — skipping", segment
            )
            return 0

    logger.info("embed_products_batch [%s]: guards passed — starting vectorization", segment)

    oai   = _get_oai_client()
    index = _get_pinecone_index()

    # Load all active products for this segment
    async with session_factory() as session:
        stmt = select(Product).where(
            Product.is_active == True,
            Product.segment == segment,
        )
        if limit:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        products: Sequence[Product] = result.scalars().all()

    if not products:
        logger.info("embed_products_batch [%s]: no active products found", segment)
        return 0

    logger.info("embed_products_batch [%s]: %d products to embed → namespace '%s'",
                segment, len(products), namespace)
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
            logger.error("OpenAI embedding batch [%s][%d] failed: %s", segment, batch_start, exc)
            continue

        vectors = [item.embedding for item in resp.data]

        # ── Pinecone upsert ───────────────────────────────────────────────────
        pc_idx = _get_pinecone_index()
        if pc_idx is None:
            logger.error("embed_products_batch [%s]: Pinecone index not available", segment)
            return upserted

        vectors_to_upsert = [
            {
                "id":     str(p.id),
                "values": vec,
                "metadata": {
                    "article":  (p.article  or "").strip(),
                    "name":     (p.name     or "").strip(),
                    "brand":    (p.brand    or "").strip(),
                    "segment":  (p.segment  or "ss").strip(),
                },
            }
            for p, vec in zip(batch, vectors)
        ]

        for pc_start in range(0, len(vectors_to_upsert), _PC_BATCH_SIZE):
            pc_batch = vectors_to_upsert[pc_start: pc_start + _PC_BATCH_SIZE]
            try:
                pc_idx.upsert(vectors=pc_batch, namespace=namespace)
            except Exception as exc:
                logger.error("Pinecone upsert [%s][%d] failed: %s", segment, pc_start, exc)

        upserted += len(batch)
        logger.info(
            "embed_products_batch [%s]: %d / %d upserted",
            segment,
            min(batch_start + _BATCH_SIZE, len(products)),
            len(products),
        )

    logger.info("embed_products_batch [%s]: done — %d products in namespace '%s'",
                segment, upserted, namespace)
    return upserted
