"""
embedder.py — OpenAI embeddings + Pinecone vector index for Phase 2 AI matching.

Vectorization guard conditions (both must be true, unless force=True):
  1. Today matches the segment's assigned weekday
  2. Product DB was updated during the previous calendar week
     (at least one successful ImportLog entry for that segment Mon–Sun of last week)

Pinecone namespace mapping:
  ss  → "products_ss"   (Слаботочные системы)  — vectorizes on Monday (0)
  os  → "products_os"   (Осветительные системы) — vectorizes on Tuesday (1)
  sil → "products_sil"  (Силовые системы)        — vectorizes on Friday (4)

Budget guard:
  Daily spend is tracked in _daily_budget_tracker (in-memory, reset at midnight).
  Before each OpenAI batch, the estimated cost is checked against the remaining budget.
  Actual token usage from the API response updates the tracker after each call.
  Budget limit: settings.EMBED_DAILY_BUDGET_USD (default $1.60).
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
    "os":  "products_os",   # Tuesday
    "sil": "products_sil",  # Friday
}
SEGMENT_WEEKDAY = {
    "ss":  0,   # Monday
    "os":  1,   # Tuesday
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
_pinecone_key_used: str = ""   # track which key was used to build the index


def reset_pinecone_client():
    """Force re-initialization of the Pinecone client on next call.
    Use after updating PINECONE_API_KEY / PINECONE_HOST without restarting."""
    global _pinecone_index, _pinecone_key_used
    _pinecone_index   = None
    _pinecone_key_used = ""
    logger.info("Pinecone client reset — will reconnect on next vectorization call")


def _get_pinecone_index():
    """Return the Pinecone Index object.

    Re-creates the client if PINECONE_API_KEY changed since last init
    (e.g. after calling reset_pinecone_client() or updating .env without restart).
    """
    global _pinecone_index, _pinecone_key_used
    current_key = settings.PINECONE_API_KEY

    # Recreate if key changed or not yet initialized
    if _pinecone_index is None or _pinecone_key_used != current_key:
        if not current_key:
            raise RuntimeError(
                "PINECONE_API_KEY is not set. Add it to .env or docker-compose."
            )
        if not settings.PINECONE_HOST:
            raise RuntimeError(
                "PINECONE_HOST is not set. Add it to .env or docker-compose. "
                "Find it in console.pinecone.io → your index → host URL."
            )
        logger.info("Pinecone: (re)connecting to host=%s", settings.PINECONE_HOST)
        pc = Pinecone(api_key=current_key)
        _pinecone_index   = pc.Index(host=settings.PINECONE_HOST)
        _pinecone_key_used = current_key
    return _pinecone_index


async def test_pinecone_connection() -> dict:
    """Quick connectivity check — returns stats or error dict."""
    try:
        idx = _get_pinecone_index()
        stats = idx.describe_index_stats()
        return {
            "ok": True,
            "total_vector_count": getattr(stats, "total_vector_count", None),
            "namespaces": {
                ns: {"vector_count": v.vector_count}
                for ns, v in (getattr(stats, "namespaces", None) or {}).items()
            },
            "host": settings.PINECONE_HOST,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "host": settings.PINECONE_HOST}


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

# ── Cost per 1M tokens by model ───────────────────────────────────────────────
_MODEL_COST_PER_1M: dict[str, float] = {
    "text-embedding-3-small": 0.020,
    "text-embedding-3-large": 0.130,
    "text-embedding-ada-002": 0.100,
}
_DEFAULT_COST_PER_1M = 0.020   # fallback if model not in dict


# ── Daily budget tracker (in-memory; resets at midnight) ─────────────────────

class _BudgetTracker:
    """Thread-safe (asyncio) daily spend tracker.

    Tracks:
      - tokens_used  : total tokens embedded today (from resp.usage)
      - cost_usd     : total cost in USD today
      - segments     : per-segment breakdown {seg: {"tokens": N, "cost": X}}
    Resets automatically when a new calendar day begins.
    """

    def __init__(self):
        self._date:    str   = ""
        self.tokens:   int   = 0
        self.cost_usd: float = 0.0
        self.segments: dict  = {}   # {seg: {"tokens": int, "cost": float}}

    def _check_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._date:
            self._date    = today
            self.tokens   = 0
            self.cost_usd = 0.0
            self.segments = {}

    def add(self, segment: str, tokens: int, cost: float):
        self._check_reset()
        self.tokens   += tokens
        self.cost_usd += cost
        if segment not in self.segments:
            self.segments[segment] = {"tokens": 0, "cost": 0.0}
        self.segments[segment]["tokens"] += tokens
        self.segments[segment]["cost"]   += cost

    def spent(self) -> float:
        self._check_reset()
        return self.cost_usd

    def remaining(self, budget: float) -> float:
        return max(0.0, budget - self.spent())

    def snapshot(self, budget: float) -> dict:
        self._check_reset()
        return {
            "date":          self._date,
            "budget_usd":    budget,
            "spent_usd":     round(self.cost_usd, 6),
            "remaining_usd": round(self.remaining(budget), 6),
            "tokens_today":  self.tokens,
            "segments":      {
                seg: {"tokens": v["tokens"], "cost_usd": round(v["cost"], 6)}
                for seg, v in self.segments.items()
            },
        }


_budget_tracker = _BudgetTracker()


def get_budget_snapshot() -> dict:
    """Return the current daily budget snapshot (for API endpoints)."""
    from app.core.config import settings
    return _budget_tracker.snapshot(settings.EMBED_DAILY_BUDGET_USD)


def _cost_per_token(model: str) -> float:
    return _MODEL_COST_PER_1M.get(model, _DEFAULT_COST_PER_1M) / 1_000_000


def _estimate_tokens(texts: list[str]) -> int:
    """Rough token estimate: 1 token ≈ 4 chars (OpenAI rule of thumb)."""
    return max(1, sum(max(1, len(t) // 4) for t in texts))


async def embed_products_batch(
    session_factory: async_sessionmaker,
    segment: str = "ss",
    limit: int = 0,
    force: bool = False,
) -> dict:
    """
    Embed all active products of a given segment via OpenAI and upsert into Pinecone.

    Uses namespace SEGMENT_NAMESPACE[segment] within the single Pinecone index.

    Guards (both must be true; skipped when force=True):
      1. Today matches the segment's assigned weekday.
      2. Product DB for this segment was imported via the app during the previous Mon–Sun.

    Budget guard (always active):
      Before each OpenAI batch the estimated cost is compared against the remaining
      daily budget (settings.EMBED_DAILY_BUDGET_USD).  If the batch would exceed the
      budget, vectorization stops and the remainder is skipped.

    Returns:
      {
        "upserted": int,       # products successfully embedded
        "skipped":  int,       # products not embedded (budget exceeded)
        "tokens":   int,       # tokens used (from API usage)
        "cost_usd": float,     # estimated cost in USD
        "budget_remaining": float,
        "budget_exceeded": bool,
      }
    """
    _empty = {
        "upserted": 0, "skipped": 0, "tokens": 0, "cost_usd": 0.0,
        "budget_remaining": _budget_tracker.remaining(settings.EMBED_DAILY_BUDGET_USD),
        "budget_exceeded": False,
    }

    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping vectorization")
        return _empty
    if not settings.PINECONE_API_KEY or not settings.PINECONE_HOST:
        logger.warning("PINECONE_API_KEY or PINECONE_HOST not set — skipping vectorization")
        return _empty

    namespace = SEGMENT_NAMESPACE.get(segment, f"products_{segment}")

    if not force:
        if not _is_segment_day(segment):
            logger.info(
                "embed_products_batch [%s]: today is %s, not the assigned day — skipping",
                segment, datetime.now().strftime("%A"),
            )
            return _empty

        if not await _db_imported_last_week(session_factory, segment):
            logger.info(
                "embed_products_batch [%s]: no import last week — skipping", segment
            )
            return _empty

    # ── Pre-check budget before even loading products ─────────────────────────
    daily_budget = settings.EMBED_DAILY_BUDGET_USD
    if _budget_tracker.remaining(daily_budget) <= 0:
        logger.warning(
            "embed_products_batch [%s]: daily budget $%.4f exhausted — skipping entirely",
            segment, daily_budget,
        )
        return {**_empty, "budget_exceeded": True}

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
        return _empty

    logger.info("embed_products_batch [%s]: %d products to embed → namespace '%s'",
                segment, len(products), namespace)

    upserted        = 0
    skipped         = 0
    total_tokens    = 0
    total_cost      = 0.0
    budget_exceeded = False
    cost_per_tok    = _cost_per_token(settings.OPENAI_EMBED_MODEL)

    for batch_start in range(0, len(products), _BATCH_SIZE):
        batch = products[batch_start: batch_start + _BATCH_SIZE]
        texts = [_product_text(p.article or "", p.name or "") for p in batch]

        # ── Budget pre-flight ─────────────────────────────────────────────────
        est_tokens = _estimate_tokens(texts)
        est_cost   = est_tokens * cost_per_tok
        remaining  = _budget_tracker.remaining(daily_budget)

        if est_cost > remaining:
            skipped += len(batch)
            budget_exceeded = True
            logger.warning(
                "embed_products_batch [%s]: batch @%d — estimated cost $%.5f > "
                "remaining $%.5f — stopping (skipped %d products)",
                segment, batch_start, est_cost, remaining, len(products) - upserted,
            )
            # Skip all remaining products too
            skipped += sum(
                min(_BATCH_SIZE, len(products) - s)
                for s in range(batch_start + _BATCH_SIZE, len(products), _BATCH_SIZE)
            )
            break

        # ── OpenAI embedding ──────────────────────────────────────────────────
        try:
            resp = await oai.embeddings.create(
                model=settings.OPENAI_EMBED_MODEL,
                input=texts,
            )
        except Exception as exc:
            logger.error("OpenAI embedding batch [%s][%d] failed: %s", segment, batch_start, exc)
            skipped += len(batch)
            continue

        # Update tracker with actual token usage from the API response
        actual_tokens = getattr(getattr(resp, "usage", None), "total_tokens", None) or est_tokens
        actual_cost   = actual_tokens * cost_per_tok
        _budget_tracker.add(segment, actual_tokens, actual_cost)
        total_tokens += actual_tokens
        total_cost   += actual_cost

        vectors = [item.embedding for item in resp.data]

        # ── Pinecone upsert ───────────────────────────────────────────────────
        pc_idx = _get_pinecone_index()
        if pc_idx is None:
            logger.error("embed_products_batch [%s]: Pinecone index not available", segment)
            break

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

        pc_errors = 0
        for pc_start in range(0, len(vectors_to_upsert), _PC_BATCH_SIZE):
            pc_batch = vectors_to_upsert[pc_start: pc_start + _PC_BATCH_SIZE]
            try:
                pc_idx.upsert(vectors=pc_batch, namespace=namespace)
            except Exception as exc:
                logger.error("Pinecone upsert [%s][%d] failed: %s", segment, pc_start, exc)
                pc_errors += len(pc_batch)

        batch_ok = len(batch) - pc_errors
        upserted += batch_ok
        skipped  += pc_errors
        if pc_errors and pc_errors == len(batch):
            # Весь батч отклонён Pinecone (напр. 401) — прекращаем попытки
            logger.error(
                "embed_products_batch [%s]: Pinecone rejected entire batch "
                "(all %d vectors failed) — aborting upsert loop",
                segment, pc_errors,
            )
            skipped += sum(
                min(_BATCH_SIZE, len(products) - s)
                for s in range(batch_start + _BATCH_SIZE, len(products), _BATCH_SIZE)
            )
            break
        logger.info(
            "embed_products_batch [%s]: %d / %d upserted  |  "
            "batch tokens=%d cost=$%.5f  |  daily spent=$%.5f remaining=$%.5f",
            segment,
            min(batch_start + _BATCH_SIZE, len(products)), len(products),
            actual_tokens, actual_cost,
            _budget_tracker.spent(), _budget_tracker.remaining(daily_budget),
        )

    logger.info(
        "embed_products_batch [%s]: done — upserted=%d skipped=%d "
        "tokens=%d cost=$%.5f budget_exceeded=%s",
        segment, upserted, skipped, total_tokens, total_cost, budget_exceeded,
    )
    return {
        "upserted":         upserted,
        "skipped":          skipped,
        "tokens":           total_tokens,
        "cost_usd":         round(total_cost, 6),
        "budget_remaining": round(_budget_tracker.remaining(daily_budget), 6),
        "budget_exceeded":  budget_exceeded,
    }
