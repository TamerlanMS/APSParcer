from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Product
from typing import List, Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)

EXACT_SCORE            = 100
CONTAINS_SCORE         = 95
FUZZY_THRESHOLD        = 80   # minimum % for article fuzzy match
NAME_FUZZY_THRESHOLD   = 93   # very strict -- name tokens must be nearly identical
NAME_PARTIAL_THRESHOLD = 96   # partial_ratio threshold for name fallback

# Length ratio guard for substring "contains" checks.
# If the shorter string is < this fraction of the longer, match is too vague.
_CONTAINS_LEN_RATIO = 0.70

# Minimum character length for a name to qualify for name-based fuzzy matching.
_NAME_MIN_LEN = 20

# Minimum fraction of query WORDS that must appear in the DB name for a partial_ratio match.
# E.g. "Кронштейн монтажный DS-1232ZJ" (3 words) vs DB "Кронштейн" (1 word):
# coverage = 1/3 = 0.33 < 0.40 -> rejected even if partial_ratio = 100.
_WORD_COVERAGE_MIN = 0.40

# KazNIISA codes must have exactly 10 digits (format XXX-XXX-XXXX).
# Codes with fewer or more digits are arbitrary placeholders -- skip them.
_KAZNISA_DIGITS_REQUIRED = 10

# Known brand names that PDF designers append to article numbers.
# E.g. "ВА47-29 1Р 16А IEK" -> try also "ВА47-29 1Р 16А" without the brand.
_BRAND_SUFFIX_RE = re.compile(
    r"\s+(IEK|EKF|DEK|HIKVISION|DAHUA|AJAX|BOLID|BOSCH|ABB|LEGRAND|SCHNEIDER|HAGER|"
    r"REXANT|TDM|KEAZ|TEXENERGO|TEKFOR|ELVERT|ANDELI|CHINT|NOARK|APATOR|EASTEC|"
    r"WAGO|PHOENIX|SIEMENS|MOELLER|EATON|RITTAL|MEANWELL|DELTA|FLUKE|FLIR|HIOKI)$",
    re.IGNORECASE,
)

# Sub-item numbering prefix: "1 / ", "2/ " etc. (assembly щит rows).
_SUBITEM_PREFIX_RE = re.compile(r"^\d+\s*/\s*", re.UNICODE)


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.upper().strip()
    t = re.sub(r'[–—−‒]', '-', t)
    t = re.sub(r'[«»“”„‟‘’`]', '', t)
    t = re.sub(r'[(){}\[\]]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'\s+W\d+\.\d+$', '', t)
    return t.strip()


def _strip_brand_suffix(norm_art: str) -> str:
    """Remove trailing brand name from a normalized article string.
    E.g. 'ЩМП-3-0 IP31 IEK' -> 'ЩМП-3-0 IP31'.
    Returns empty string if nothing was stripped (no change).
    """
    stripped = _BRAND_SUFFIX_RE.sub("", norm_art).strip()
    return stripped if stripped != norm_art else ""


def _clean_name_for_match(name_raw: str) -> str:
    """Strip sub-item numbering prefix ('1 / ', '2/ ' etc.) from assembly sub-rows."""
    return _SUBITEM_PREFIX_RE.sub("", name_raw.strip())


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
        "unit":         (p.unit         or "шт.").strip(),
        "brand":        (p.brand        or "").strip(),
        "kaznisa":      p.kaznisa,
        "rrts":         p.rrts,
        "mrc":          p.mrc,
        "opt":          p.opt,
        "partner":      p.partner,
        "multiplicity": p.multiplicity,
        "kaznisa_code": (p.kaznisa_code or "").strip(),
    }


class _ProductIndex:
    """Built once per match_items call; holds pre-normalised product strings."""

    __slots__ = ("products", "norm_art", "norm_name", "norm_code",
                 "art_exact", "code_exact", "name_exact")

    def __init__(self, products: List[Product]):
        self.products  = products
        self.norm_art  = [normalize(p.article      or '') for p in products]
        self.norm_name = [normalize(p.name         or '') for p in products]
        self.norm_code = [normalize(p.kaznisa_code or '') for p in products]

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

    Matching priority:
      1.  Exact article match         (O(1) -- authoritative)
      1b. Exact article after brand-suffix strip  ('ВА47-29 IEK' -> 'ВА47-29')
      1c. Exact KazNIISA code match   (O(1) -- only 10-digit codes, only when article missing)
      2.  Substring / fuzzy article   (O(n) -- model numbers, tries stripped variant too)
      3.  Name-based fallback         (O(n) -- only when article gives nothing)
    """
    norm_q = normalize(article_raw)
    # Strip assembly sub-item prefix ("1 / Корпус...") before name matching
    norm_name_q = normalize(_clean_name_for_match(name_raw))

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

    # ---- 1b. Exact article match after brand-suffix strip -----------------
    # Handles "ЩМП-3-0 IP31 IEK" where DB stores "ЩМП-3-0 IP31"
    norm_q_stripped = _strip_brand_suffix(norm_q) if norm_q else ""
    if norm_q_stripped and norm_q_stripped in index.art_exact:
        for i in index.art_exact[norm_q_stripped]:
            candidates.append({"product": products[i], "score": EXACT_SCORE, "method": "exact"})
        return candidates[:1]

    # ---- 1c. Exact KazNIISA code match (O(1)) -- only when article missing -
    # Only used as a fallback; code matching is less reliable than article matching.
    # Guard: the code must contain EXACTLY 10 digits (standard format XXX-XXX-XXXX).
    # Codes with fewer/more digits are arbitrary placeholders -- skip them entirely.
    if not norm_q and kaznisa_code_raw:
        norm_code_q  = normalize(kaznisa_code_raw)
        _digits_only = re.sub(r'\D', '', norm_code_q)
        if len(_digits_only) == _KAZNISA_DIGITS_REQUIRED and norm_code_q in index.code_exact:
            for i in index.code_exact[norm_code_q]:
                candidates.append({"product": products[i], "score": EXACT_SCORE, "method": "code_exact"})
            return candidates[:1]

    # ---- 2. Substring / fuzzy scan by article (O(n)) ----------------------
    # Try both the original norm_q and the brand-stripped variant so that
    # 'ВА47-29 1Р 16А 4,5КА С IEK' can still fuzzy-match 'ВА47-29 1Р 16А 4,5КА С'.
    queries_to_try = [q for q in (norm_q, norm_q_stripped) if q]
    if queries_to_try:
        for i, p in enumerate(products):
            na = norm_art[i]
            nn = norm_name[i]

            matched = False
            for nq in queries_to_try:
                # Article contains check -- only when lengths are reasonably similar
                if na and (nq in na or na in nq):
                    _len_ratio = min(len(nq), len(na)) / max(len(nq), len(na), 1)
                    if _len_ratio >= _CONTAINS_LEN_RATIO:
                        candidates.append({"product": p, "score": CONTAINS_SCORE, "method": "contains"})
                        matched = True
                        break

                # Fuzzy article
                if na:
                    s = fuzz.token_sort_ratio(nq, na)
                    if s >= FUZZY_THRESHOLD:
                        candidates.append({"product": p, "score": s, "method": "fuzzy_article"})
                        matched = True
                        break

            if matched:
                continue

            # Article query vs DB name (catches mislabeled article fields)
            if norm_q and nn:
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
    # dozens of different products -- better to return not_found and let the manager decide.
    if norm_name_q and len(norm_name_q) >= _NAME_MIN_LEN:
        name_cands: List[Dict] = []

        # Exact name match (O(1))
        if norm_name_q in index.name_exact:
            for i in index.name_exact[norm_name_q]:
                name_cands.append({"product": products[i], "score": 99, "method": "name_exact"})
            name_cands.sort(key=lambda x: x['score'], reverse=True)
            return name_cands[:1]

        # Substring / fuzzy scan by name (O(n)) -- strict thresholds
        for i, p in enumerate(products):
            nn = norm_name[i]
            if not nn:
                continue

            # Name substring -- with length ratio guard.
            # Avoids "Камера" matching "Камера купольная PTZ IP66 30x zoom outdoor".
            if norm_name_q in nn or nn in norm_name_q:
                _len_ratio = min(len(norm_name_q), len(nn)) / max(len(norm_name_q), len(nn), 1)
                if _len_ratio >= _CONTAINS_LEN_RATIO:
                    name_cands.append({"product": p, "score": CONTAINS_SCORE - 2, "method": "name_contains"})
                # Always stop here when substring is found -- good or bad ratio.
                # Without this continue, a bad-ratio substring falls through to partial_ratio
                # which returns 100 (since the short string is fully inside the long one), giving
                # a false "exact" match on a single generic word like "Кронштейн".
                continue

            # Strict fuzzy token sort
            s = fuzz.token_sort_ratio(norm_name_q, nn)
            if s >= NAME_FUZZY_THRESHOLD:
                name_cands.append({"product": p, "score": s, "method": "name_fuzzy"})
                continue

            # Strict partial ratio -- with word-coverage guard.
            # partial_ratio finds the best-matching window, so it gives 100 when any word matches.
            # We additionally require that at least _WORD_COVERAGE_MIN of the QUERY words appear
            # in the DB name, preventing single-word matches from showing as "Найдено".
            s2 = fuzz.partial_ratio(norm_name_q, nn)
            if s2 >= NAME_PARTIAL_THRESHOLD:
                q_tokens = set(norm_name_q.split())
                n_tokens  = set(nn.split())
                coverage  = len(q_tokens & n_tokens) / max(len(q_tokens), 1)
                if coverage >= _WORD_COVERAGE_MIN:
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

            cands_data = [
                {**product_to_dict(c["product"]), "score": c["score"], "method": c["method"]}
                for c in candidates
            ]
            best = product_to_dict(candidates[0]["product"])

            # Log if matched product has no price data (helps diagnose empty price columns)
            _price_vals = {k: best.get(k) for k in ("kaznisa", "rrts", "mrc", "opt", "partner")}
            if not any(_price_vals.values()):
                logger.warning(
                    "Matched product has NO prices: article=%r name=%r brand=%r — "
                    "kaznisa=%s rrts=%s mrc=%s opt=%s partner=%s",
                    best.get("article"), best.get("name"), best.get("brand"),
                    _price_vals["kaznisa"], _price_vals["rrts"],
                    _price_vals["mrc"], _price_vals["opt"], _price_vals["partner"],
                )

        results.append({
            "pos":              item.get("pos"),
            "name_raw":         item.get("name_raw", ""),
            "article_raw":      item.get("article_raw", ""),
            "kaznisa_code_raw": item.get("kaznisa_code_raw", ""),
            "qty":              item.get("qty", 1),
            "unit":             item.get("unit", ""),
            "status":           status,
            "match_method":     match_method,
            "best_match":       best,
            "candidates":       cands_data,
        })

    return results
