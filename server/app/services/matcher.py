from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Product
from typing import List, Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)

EXACT_SCORE          = 100
CONTAINS_SCORE       = 95
FUZZY_THRESHOLD      = 80   # minimum % for article fuzzy match (was 68 — raised to avoid single-word matches)
NAME_FUZZY_THRESHOLD = 93   # very strict — name tokens must be nearly identical (was 85)
NAME_PARTIAL_THRESHOLD = 96 # partial_ratio threshold for name fallback (was 90)

# Length ratio guard for substring "contains" checks:
# if the shorter string is < this fraction of the longer, substring match is too vague.
# E.g. "Камера" (6 ch) in "Камера купольная PTZ IP66 outdoor" (33 ch) → ratio 0.18 → rejected.
_CONTAINS_LEN_RATIO = 0.70  # was 0.55 — tighter: strings must be within 30% of each other in length

# Minimum character length for a name to qualify for name-based fuzzy matching.
# Short generic names ("Датчик", "Кабель 10м") match too many products — skip them entirely.
_NAME_MIN_LEN = 20


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
    kaznisa_code_raw: str = '',   # kept for API compatibility, not used for matching
    name_raw: str = '',
) -> List[Dict]:
    """Return ranked candidates.

    Matching priority:
      1. Exact article match         (O(1) — authoritative)
      2. Substring / fuzzy article   (O(n) — model numbers)
         Also checks article query against DB names (mislabeled fields).
      3. Name-based fallback         (O(n) — only when article gives nothing)
         High thresholds (NAME_FUZZY_THRESHOLD / NAME_PARTIAL_THRESHOLD) prevent
         false positives from generic names that appear in many different products.
         If no name candidate meets the threshold, returns empty → "not_found",
         so the manager can select the correct item manually.

    KazNIISA code matching is intentionally disabled: project designers often
    enter arbitrary or placeholder codes that do not correspond to real DB items.
    """
    norm_q      = normalize(article_raw)
    norm_name_q = normalize(name_raw)

    if not norm_q and not norm_name_q:
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

    # ---- 2. Substring / fuzzy scan by article (O(n)) ----------------------
    if norm_q:
        for i, p in enumerate(products):
            na = norm_art[i]
            nn = norm_name[i]

            # Article contains — only when lengths are reasonably similar
            if na and (norm_q in na or na in norm_q):
                _len_ratio = min(len(norm_q), len(na)) / max(len(norm_q), len(na), 1)
                if _len_ratio >= _CONTAINS_LEN_RATIO:
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

    # ---- 3. Name-based fallback (only when article search found nothing) ----
    # Very strict: only engage when the name is specific enough (>= _NAME_MIN_LEN chars)
    # and scores are very high. Short/generic names ("Датчик", "Кабель ВВГнг") match
    # dozens of different products — better to return not_found and let the manager decide.
    if norm_name_q and len(norm_name_q) >= _NAME_MIN_LEN:
        name_cands: List[Dict] = []

        # Exact name match (O(1))
        if norm_name_q in index.name_exact:
            for i in index.name_exact[norm_name_q]:
                name_cands.append({"product": products[i], "score": 99, "method": "name_exact"})
            name_cands.sort(key=lambda x: x['score'], reverse=True)
            return name_cands[:1]

        # Substring / fuzzy scan by name (O(n)) — strict thresholds
        for i, p in enumerate(products):
            nn = norm_name[i]
            if not nn:
                continue

            # Name substring (one fully contained in the other) — with length ratio guard
            # Avoids "Камера" matching "Камера купольная PTZ IP66 30x zoom outdoor"
            if norm_name_q in nn or nn in norm_name_q:
                _len_ratio = min(len(norm_name_q), len(nn)) / max(len(norm_name_q), len(nn), 1)
                if _len_ratio >= _CONTAINS_LEN_RATIO:
                    name_cands.append({"product": p, "score": CONTAINS_SCORE - 2, "method": "name_contains"})
                    continue

            # Strict fuzzy token sort
            s = fuzz.token_sort_ratio(norm_name_q, nn)
            if s >= NAME_FUZZY_THRESHOLD:
                name_cands.append({"product": p, "score": s, "method": "name_fuzzy"})
                continue

            # Strict partial ratio
            s2 = fuzz.partial_ratio(norm_name_q, nn)
            if s2 >= NAME_PARTIAL_THRESHOLD:
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
            status       = "not_found"
            best         = None
            cands_data   = []
            match_method = None
        else:
            best_score = candidates[0]['score']
            close      = [c for c in candidates if best_score - c['score'] <= 5]

            if best_score >= EXACT_SCORE:
                status = "exact"
            elif len(close) > 1:
                status = "multiple"
            else:
                status = "fuzzy"

            match_method = candidates[0].get("method")
            best         = product_to_dict(candidates[0]['product'])
            cands_data   = [
                {**product_to_dict(c["product"]), "score": c["score"], "method": c["method"]}
                for c in candidates
            ]

        results.append({
            **item,
            "status":       status,
            "match_method": match_method,
            "best_match":   best,
            "candidates":   cands_data,
        })

    return results
