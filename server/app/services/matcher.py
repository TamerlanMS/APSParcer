from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Product
from typing import List, Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)

EXACT_SCORE     = 100
CONTAINS_SCORE  = 95
FUZZY_THRESHOLD = 68   # minimum % for fuzzy match


def normalize(text: str) -> str:
    """Normalize string for comparison."""
    if not text:
        return ""
    t = text.upper().strip()
    t = re.sub(r'[\u2013\u2014\u2212\u2012]', '-', t)
    t = re.sub(r'[\u00ab\u00bb\u201c\u201d\u201e\u201f\u2018\u2019`]', '', t)
    t = re.sub(r'[(){}\[\]]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'\s+W\d+\.\d+$', '', t)
    return t.strip()


async def get_all_products(db: AsyncSession) -> List[Product]:
    result = await db.execute(
        select(Product).where(Product.is_active == True)
    )
    return result.scalars().all()


def product_to_dict(p: Product) -> Dict:
    return {
        "id":           p.id,
        "article":      (p.article      or "").strip(),
        "name":         (p.name         or "").strip(),
        "unit":         (p.unit         or "\u0448\u0442.").strip(),
        "brand":        (p.brand        or "").strip(),
        "kaznisa":      p.kaznisa,
        "rrts":         p.rrts,
        "mrc":          p.mrc,
        "opt":          p.opt,
        "partner":      p.partner,
        "multiplicity": p.multiplicity,
        "kaznisa_code": (p.kaznisa_code or "").strip(),
    }


# ---------------------------------------------------------------------------
# Pre-normalised product cache
# ---------------------------------------------------------------------------

class _ProductIndex:
    """Built once per match_items call; holds pre-normalised product strings."""

    __slots__ = ("products", "norm_art", "norm_name", "norm_code",
                 "art_exact", "code_exact", "name_exact")

    def __init__(self, products: List[Product]):
        self.products  = products
        self.norm_art  = [normalize(p.article      or '') for p in products]
        self.norm_name = [normalize(p.name         or '') for p in products]
        self.norm_code = [normalize(p.kaznisa_code or '') for p in products]

        # O(1) lookup dicts: norm_value -> list of indices
        self.art_exact: Dict[str, List[int]] = {}
        for i, na in enumerate(self.norm_art):
            if na:
                self.art_exact.setdefault(na, []).append(i)

        self.code_exact: Dict[str, List[int]] = {}
        for i, nc in enumerate(self.norm_code):
            if nc:
                self.code_exact.setdefault(nc, []).append(i)

        self.name_exact: Dict[str, List[int]] = {}
        for i, nn in enumerate(self.norm_name):
            if nn:
                self.name_exact.setdefault(nn, []).append(i)


def find_candidates(
    article_raw: str,
    index: _ProductIndex,
    kaznisa_code_raw: str = '',
    name_raw: str = '',
) -> List[Dict]:
    """Return ranked candidates.

    Steps:
      1. Exact article match (O(1))
      2. Exact kaznisa_code match (O(1))
      3. Substring / fuzzy scan by article query (O(n))
         Also tries article query against DB names (catches mislabeled fields)
      4. Name-based fallback using name_raw (runs only when steps 1-3 give nothing)
    """
    norm_q      = normalize(article_raw)
    norm_code   = normalize(kaznisa_code_raw)
    norm_name_q = normalize(name_raw)

    if not norm_q and not norm_code and not norm_name_q:
        return []

    products  = index.products
    norm_art  = index.norm_art
    norm_name = index.norm_name

    candidates: List[Dict] = []

    # ---- 1. Exact article match (O(1)) ------------------------------------
    if norm_q and norm_q in index.art_exact:
        for i in index.art_exact[norm_q]:
            candidates.append({"product": products[i], "score": EXACT_SCORE, "method": "exact"})
        return candidates[:1]

    # ---- 2. Exact kaznisa_code match (O(1)) -------------------------------
    if norm_code and norm_code in index.code_exact:
        for i in index.code_exact[norm_code]:
            candidates.append({"product": products[i], "score": 98, "method": "code_exact"})
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            return candidates[:1]

    # ---- 3. Substring / fuzzy scan by article (O(n)) ----------------------
    if norm_q:
        for i, p in enumerate(products):
            na = norm_art[i]
            nn = norm_name[i]

            # Article contains
            if na and (norm_q in na or na in norm_q):
                candidates.append({"product": p, "score": CONTAINS_SCORE, "method": "contains"})
                continue

            # Fuzzy article
            if na:
                s = fuzz.token_sort_ratio(norm_q, na)
                if s >= FUZZY_THRESHOLD:
                    candidates.append({"product": p, "score": s, "method": "fuzzy_article"})
                    continue

            # Article query vs DB name (catches mislabeled article fields)
            if nn:
                s = fuzz.partial_ratio(norm_q, nn)
                if s >= FUZZY_THRESHOLD + 10:
                    candidates.append({"product": p, "score": s, "method": "fuzzy_name_from_article"})

        candidates.sort(key=lambda x: x['score'], reverse=True)

        exact_only = [c for c in candidates if c['score'] >= EXACT_SCORE]
        if exact_only:
            return exact_only[:1]

        if candidates:
            return candidates[:5]

    # ---- 4. Name-based fallback (runs when article search found nothing) ----
    if norm_name_q:
        name_cands: List[Dict] = []

        # Exact name match (O(1))
        if norm_name_q in index.name_exact:
            for i in index.name_exact[norm_name_q]:
                name_cands.append({"product": products[i], "score": 99, "method": "name_exact"})
            name_cands.sort(key=lambda x: x['score'], reverse=True)
            return name_cands[:1]

        # Substring / fuzzy scan by name (O(n))
        for i, p in enumerate(products):
            nn = norm_name[i]
            if not nn:
                continue

            # Name substring
            if norm_name_q in nn or nn in norm_name_q:
                name_cands.append({"product": p, "score": CONTAINS_SCORE - 2, "method": "name_contains"})
                continue

            # Fuzzy token sort
            s = fuzz.token_sort_ratio(norm_name_q, nn)
            if s >= FUZZY_THRESHOLD:
                name_cands.append({"product": p, "score": s, "method": "name_fuzzy"})
                continue

            # Partial ratio (good for long names with extra words)
            s2 = fuzz.partial_ratio(norm_name_q, nn)
            if s2 >= FUZZY_THRESHOLD + 10:
                name_cands.append({"product": p, "score": s2, "method": "name_partial"})

        name_cands.sort(key=lambda x: x['score'], reverse=True)
        return name_cands[:5]

    return candidates[:5]


async def match_items(
    pdf_items: List[Dict],
    db: AsyncSession,
) -> List[Dict]:
    """
    Find DB candidates for every PDF position.
    Products are fetched once and pre-normalised; exact lookups use O(1) dicts.
    Falls back to name-based search when article search yields no candidates.
    """
    all_products = await get_all_products(db)
    index        = _ProductIndex(all_products)
    logger.info("match_items: %d PDF items vs %d products", len(pdf_items), len(all_products))

    results = []

    for item in pdf_items:
        candidates = find_candidates(
            item.get("article_raw", "") or "",
            index,
            kaznisa_code_raw=item.get("kaznisa_code_raw", "") or "",
            name_raw=item.get("name_raw", "") or "",
        )

        if not candidates:
            status     = "not_found"
            best       = None
            cands_data = []
        else:
            best_score = candidates[0]['score']
            close      = [c for c in candidates if best_score - c['score'] <= 5]

            if best_score >= EXACT_SCORE:
                status = "exact"
            elif len(close) > 1:
                status = "multiple"
            else:
                status = "fuzzy"

            best       = product_to_dict(candidates[0]['product'])
            cands_data = [
                {**product_to_dict(c["product"]), "score": c["score"], "method": c["method"]}
                for c in candidates
            ]

        results.append({
            **item,
            "status":     status,
            "best_match": best,
            "candidates": cands_data,
        })

    return results
