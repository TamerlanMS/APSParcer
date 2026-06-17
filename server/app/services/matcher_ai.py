"""
matcher_ai.py — Phase 2 AI-powered hybrid matcher.

Matching pipeline per item:
  1. Classic matcher (rapidfuzz) — fast, free, handles exact/fuzzy articles
  2. Exact article match → returned as-is (authoritative)
  3. Everything else (fuzzy, multiple, not_found) → AI verification:
       a. Vector search (Pinecone cosine similarity) — semantic
       b. If top vector score < AI_CONFIDENCE_THRESHOLD → not_found
       c. If single clear winner → return it
       d. If top-3 are close → GPT-4o-mini reranking for final decision
  4. Returns enriched result dict with ai_reason and ai_confidence fields.

Only exact article matches skip AI — all fuzzy/multiple/not_found are verified by AI.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Product
from app.services.matcher import (
    match_items as classic_match_items,
    product_to_dict,
    get_all_products,
    _ProductIndex,
    find_candidates,
    normalize,
    EXACT_SCORE,
)
from app.services.embedder import embed_text, _product_text, _get_pinecone_index

logger = logging.getLogger(__name__)

# Classic result score above this → skip AI (already confident)
CLASSIC_PASSTHROUGH_SCORE = 88

# If the vector similarity score is below this, no candidate is close enough
VECTOR_MIN_SCORE = settings.AI_CONFIDENCE_THRESHOLD  # default 0.72

# How many vector candidates to fetch before reranking
VECTOR_TOP_K = 8


# ── Vector search via Pinecone ────────────────────────────────────────────────

async def _vector_search(
    query_vec: List[float],
    db: AsyncSession,
    top_k: int = VECTOR_TOP_K,
) -> List[Dict]:
    """
    Query Pinecone for the top_k closest product vectors.
    Returns list of dicts: {id, similarity, article, name, brand, unit}.
    Pinecone client is synchronous → runs in a thread executor.
    """
    try:
        index = _get_pinecone_index()
        result = await asyncio.wait_for(
            asyncio.to_thread(
                index.query,
                vector=query_vec,
                top_k=top_k,
                include_metadata=True,
            ),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        logger.error("Pinecone query timed out after 20s")
        return []
    except Exception as exc:
        logger.error("Pinecone query failed: %s", exc)
        return []

    candidates = []
    for match in result.matches:
        meta = match.metadata or {}
        candidates.append({
            "id":         int(match.id),
            "similarity": float(match.score),
            "article":    meta.get("article", ""),
            "name":       meta.get("name", ""),
            "brand":      meta.get("brand", ""),
            "unit":       meta.get("unit", "шт."),
        })
    return candidates


# ── GPT-4o-mini reranker ──────────────────────────────────────────────────────

async def _gpt_rerank(
    query_text: str,
    candidates: List[Dict],
) -> Optional[Dict]:
    """
    Ask GPT-4o-mini to pick the best candidate or return None if none fit.
    Returns the chosen candidate dict (with ai_reason added), or None.
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    except Exception as exc:
        logger.error("GPT reranker: cannot create OpenAI client: %s", exc)
        return None

    cand_lines = "\n".join(
        f"{i+1}. [{c.get('article','')}] {c.get('name','')} "
        f"(бренд: {c.get('brand','')}, sim={c.get('similarity',0):.2f})"
        for i, c in enumerate(candidates)
    )

    prompt = (
        "Ты — система подбора товаров для корпоративных заявок. "
        "Выбери ОДИН наиболее подходящий товар из списка кандидатов для данной позиции спецификации. "
        "Если ни один не подходит достаточно близко — ответь 'not_found'.\n\n"
        f"Позиция из спецификации: «{query_text}»\n\n"
        f"Кандидаты:\n{cand_lines}\n\n"
        "Ответь строго в формате JSON:\n"
        '{"choice": <номер кандидата 1-N или "not_found">, "reason": "<краткое объяснение>"}'
    )

    try:
        resp = await client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as exc:
        logger.error("GPT reranker failed: %s", exc)
        return None

    choice = data.get("choice")
    reason = data.get("reason", "")

    if choice == "not_found" or not isinstance(choice, int):
        return None

    idx = int(choice) - 1
    if 0 <= idx < len(candidates):
        result = dict(candidates[idx])
        result["ai_reason"] = reason
        return result

    return None


# ── Per-item AI matching ───────────────────────────────────────────────────────

async def _match_one_ai(
    item: Dict,
    classic_result: Dict,
    db: AsyncSession,
) -> Dict:
    """
    Applies AI matching on top of a classic result that needs improvement.
    Returns an enriched result dict.
    """
    article_raw = item.get("article_raw", "") or ""
    name_raw    = item.get("name_raw", "") or ""
    query_text  = _product_text(article_raw, name_raw)

    if not query_text.strip():
        return {**classic_result, "ai_used": False}

    # Embed the query
    try:
        query_vec = await embed_text(query_text)
    except Exception as exc:
        logger.warning("embed_text failed for '%s': %s", query_text[:60], exc)
        return {**classic_result, "ai_used": False}

    # Vector search
    vector_candidates = await _vector_search(query_vec, db, top_k=VECTOR_TOP_K)

    if not vector_candidates:
        return {**classic_result, "ai_used": True, "ai_reason": "no embeddings in DB"}

    best = vector_candidates[0]
    best_sim = float(best.get("similarity", 0))

    # Below threshold → not_found
    if best_sim < VECTOR_MIN_SCORE:
        return {
            **item,
            "status":     "not_found",
            "best_match": None,
            "candidates": [],
            "ai_used":    True,
            "ai_confidence": round(best_sim, 3),
            "ai_reason":  f"Лучшее совпадение ({best_sim:.0%}) ниже порога ({VECTOR_MIN_SCORE:.0%})",
        }

    # Check how close the second candidate is
    second_sim = float(vector_candidates[1].get("similarity", 0)) if len(vector_candidates) > 1 else 0
    gap = best_sim - second_sim

    # Clear winner (gap > 0.05 and score is good)
    if gap > 0.05 or best_sim >= 0.90:
        best_product_id = best["id"]
        # Build a proper product dict (need full Product for product_to_dict)
        result = await db.execute(
            text("SELECT * FROM products WHERE id = :pid"), {"pid": best_product_id}
        )
        row = result.mappings().first()
        if row is None:
            return {**classic_result, "ai_used": False}

        product_dict = {
            "id":           row["id"],
            "article":      (row["article"] or "").strip(),
            "name":         (row["name"] or "").strip(),
            "unit":         (row["unit"] or "шт.").strip(),
            "brand":        (row["brand"] or "").strip(),
            "kaznisa":      row["kaznisa"],
            "rrts":         row["rrts"],
            "mrc":          row["mrc"],
            "opt":          row["opt"],
            "partner":      row["partner"],
            "multiplicity": row["multiplicity"],
            "kaznisa_code": (row["kaznisa_code"] or "").strip(),
        }
        return {
            **item,
            "status":        "ai_match",
            "match_method":  "ai_vector",
            "best_match":    product_dict,
            "candidates":    [{**product_dict, "score": round(best_sim * 100), "method": "vector"}],
            "ai_used":       True,
            "ai_confidence": round(best_sim, 3),
            "ai_reason":     f"Семантическое совпадение {best_sim:.0%}",
        }

    # Ambiguous top results → ask GPT-4o-mini
    top3 = vector_candidates[:3]
    gpt_choice = await _gpt_rerank(query_text, top3)

    if gpt_choice is None:
        return {
            **item,
            "status":        "not_found",
            "match_method":  None,
            "best_match":    None,
            "candidates":    [],
            "ai_used":       True,
            "ai_confidence": round(best_sim, 3),
            "ai_reason":     "ИИ не нашёл подходящего товара среди кандидатов",
        }

    chosen_id = gpt_choice["id"]
    result = await db.execute(
        text("SELECT * FROM products WHERE id = :pid"), {"pid": chosen_id}
    )
    row = result.mappings().first()
    if row is None:
        return {**classic_result, "ai_used": False}

    product_dict = {
        "id":           row["id"],
        "article":      (row["article"] or "").strip(),
        "name":         (row["name"] or "").strip(),
        "unit":         (row["unit"] or "шт.").strip(),
        "brand":        (row["brand"] or "").strip(),
        "kaznisa":      row["kaznisa"],
        "rrts":         row["rrts"],
        "mrc":          row["mrc"],
        "opt":          row["opt"],
        "partner":      row["partner"],
        "multiplicity": row["multiplicity"],
        "kaznisa_code": (row["kaznisa_code"] or "").strip(),
    }
    return {
        **item,
        "status":        "ai_match",
        "match_method":  "ai_reranked",
        "best_match":    product_dict,
        "candidates":    [{**product_dict, "score": round(best_sim * 100), "method": "gpt_rerank"}],
        "ai_used":       True,
        "ai_confidence": round(best_sim, 3),
        "ai_reason":     gpt_choice.get("ai_reason", "Выбрано ИИ"),
    }


# ── Public entry point ────────────────────────────────────────────────────────

async def match_items_ai(
    pdf_items: List[Dict],
    db: AsyncSession,
) -> List[Dict]:
    """
    Hybrid AI matcher for a list of PDF items.

    For each item:
      - Run classic matcher first (free, instant)
      - Exact article match → keep as-is (authoritative, no AI cost)
      - Fuzzy / multiple / not_found → AI verification (vector + optional GPT reranking)

    Returns list of result dicts, same shape as classic match_items() but with
    extra keys: ai_used (bool), ai_confidence (float 0-1), ai_reason (str).
    """
    # Step 1: run classic matcher for all items
    logger.info("match_items_ai: START — %d items", len(pdf_items))
    classic_results = await classic_match_items(pdf_items, db)
    logger.info("match_items_ai: classic done")

    if not settings.OPENAI_API_KEY:
        logger.warning("match_items_ai: OPENAI_API_KEY not set, returning classic results")
        return [{**r, "ai_used": False} for r in classic_results]

    final_results = []

    for _idx, (item, classic) in enumerate(zip(pdf_items, classic_results)):
        logger.info(
            "match_items_ai: [%d/%d] '%s'",
            _idx + 1, len(pdf_items),
            (item.get("name_raw") or item.get("article_raw") or "?")[:50],
        )
        classic_status  = classic.get("status")
        classic_score   = 0
        if classic.get("candidates"):
            classic_score = classic["candidates"][0].get("score", 0)

        # Pass through ONLY exact article matches — they are authoritative.
        # Fuzzy/multiple/not_found all go through AI verification.
        if classic_status == "exact":
            final_results.append({**classic, "ai_used": False, "ai_reason": "точное совпадение"})
            continue

        # Everything else (fuzzy, multiple, not_found): invoke AI
        try:
            ai_result = await _match_one_ai(item, classic, db)
            final_results.append(ai_result)
        except Exception as exc:
            logger.error("AI match failed for item '%s': %s", item.get("article_raw", "?"), exc)
            final_results.append({**classic, "ai_used": False, "ai_reason": f"ошибка ИИ: {exc}"})

    logger.info("match_items_ai: DONE — %d results", len(final_results))
    return final_results
