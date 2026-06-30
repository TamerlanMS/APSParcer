from rapidfuzz import fuzz
from rapidfuzz import process as _rfp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Product
from typing import List, Dict, Optional
import logging
import re
import time

logger = logging.getLogger(__name__)

# ── In-process product index cache ───────────────────────────────────────────
# Отдельный _ProductIndex на каждый сегмент (ss/os/sil + "all").
# Загружаем только нужный сегмент из БД — не весь каталог целиком.
# Инвалидируется вызовом invalidate_product_cache() после импорта новой базы.

_CACHE_TTL_SEC = 6 * 3600   # запасной TTL — 6 часов
# ключ → (index, timestamp)
_seg_cache: Dict[str, tuple] = {}


def invalidate_product_cache() -> None:
    """Сбросить кэш индекса товаров (вызывать после импорта базы)."""
    global _seg_cache
    _seg_cache = {}
    logger.info("product cache: invalidated (all segments)")

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

# Cyrillic character range for optional stripping in sil-segment matching.
_CYRILLIC_RE = re.compile(r"[А-ЯЁа-яё]")
# Minimum length of a Cyrillic-stripped article to attempt matching (avoid garbage like "-").
_NOCYR_MIN_LEN = 3


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


async def get_products_for_segments(
    db: AsyncSession,
    segments: List[str],
) -> List[Product]:
    """Загружает только товары нужных сегментов из БД."""
    q = select(Product).where(Product.is_active == True)
    if segments:
        from sqlalchemy import or_
        q = q.where(or_(*(Product.segment == s for s in segments)))
    result = await db.execute(q)
    return result.scalars().all()


async def get_product_index(
    db: AsyncSession,
    segments: Optional[List[str]] = None,
) -> "_ProductIndex":
    """Возвращает _ProductIndex только для запрошенных сегментов.

    Кэш хранится отдельно для каждого набора сегментов (ключ — frozenset).
    Это позволяет не грузить все 166K товаров когда менеджеру нужен только
    один сегмент (~50K).
    """
    global _seg_cache
    segs = sorted(set(segments)) if segments else ["ss"]
    cache_key = ",".join(segs)
    now = time.monotonic()

    entry = _seg_cache.get(cache_key)
    if entry is not None:
        idx, ts = entry
        if (now - ts) < _CACHE_TTL_SEC:
            logger.debug("product cache: HIT key=%s (%d products)", cache_key, len(idx.products))
            return idx

    logger.info("product cache: MISS key=%s — loading from DB", cache_key)
    products = await get_products_for_segments(db, segs)
    idx = _ProductIndex(products)
    _seg_cache[cache_key] = (idx, now)
    logger.info("product cache: built index key=%s (%d products)", cache_key, len(products))
    return idx


def product_to_dict(p: Product) -> Dict:
    return {
        "id":           p.id,
        "article":      (p.article      or "").strip(),
        "name":         (p.name         or "").strip(),
        "unit":         (p.unit         or "шт.").strip(),
        "brand":        (p.brand        or "").strip(),
        "segment":      (p.segment      or "ss").strip(),
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
                 "norm_art_nocyr",
                 "art_exact", "art_nocyr_exact", "code_exact", "name_exact")

    def __init__(self, products: List[Product]):
        self.products  = products
        self.norm_art  = [normalize(p.article      or '') for p in products]
        self.norm_name = [normalize(p.name         or '') for p in products]
        self.norm_code = [normalize(p.kaznisa_code or '') for p in products]

        # Cyrillic-stripped variants of articles (used for sil-segment matching).
        self.norm_art_nocyr = [_CYRILLIC_RE.sub('', na).strip() for na in self.norm_art]

        self.art_exact: Dict[str, List[int]] = {}
        for i, na in enumerate(self.norm_art):
            if na:
                self.art_exact.setdefault(na, []).append(i)

        # O(1) lookup for Cyrillic-stripped article exact matches.
        self.art_nocyr_exact: Dict[str, List[int]] = {}
        for i, na in enumerate(self.norm_art_nocyr):
            if na and len(na) >= _NOCYR_MIN_LEN:
                self.art_nocyr_exact.setdefault(na, []).append(i)

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
    strip_cyrillic: bool = False,
) -> List[Dict]:
    """Return ranked candidates.

    Matching priority:
      1.  Exact article match         (O(1) -- authoritative)
      1b. Exact article after brand-suffix strip  ('ВА47-29 IEK' -> 'ВА47-29')
      1c. Exact KazNIISA code match   (O(1) -- only 10-digit codes, only when article missing)
      2.  Substring / fuzzy article   (O(n) -- model numbers, tries stripped variant too)
      2d. Cyrillic-stripped article match (only when strip_cyrillic=True, e.g. os segment)
      3.  Name-based fallback         (O(n) -- only when article gives nothing)
    """
    norm_q = normalize(article_raw)
    # Strip assembly sub-item prefix ("1 / Корпус...") before name matching
    norm_name_q = normalize(_clean_name_for_match(name_raw))

    if not norm_q and not norm_name_q:
        return []

    # Cyrillic-stripped query variant (used only when strip_cyrillic=True).
    norm_q_nocyr = _CYRILLIC_RE.sub('', norm_q).strip() if strip_cyrillic else ""

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

    # ---- 2. Substring / fuzzy scan by article (BATCH -- O(1) Python overhead) ---
    # Uses rapidfuzz.process.extract which runs all comparisons in C without
    # per-call Python overhead.  For 110k products this is ~30x faster than a loop.
    queries_to_try = [q for q in (norm_q, norm_q_stripped) if q]
    if queries_to_try:
        seen_art: set = set()

        for nq in queries_to_try:
            # 2a. Substring contains check -- fast C string search, much cheaper than fuzzy
            for i, na in enumerate(norm_art):
                if i in seen_art or not na:
                    continue
                if nq in na or na in nq:
                    _len_ratio = min(len(nq), len(na)) / max(len(nq), len(na), 1)
                    if _len_ratio >= _CONTAINS_LEN_RATIO:
                        candidates.append({"product": products[i], "score": CONTAINS_SCORE, "method": "contains"})
                        seen_art.add(i)

            # 2b. Batch fuzzy on articles -- single C-level call for all 110k strings
            for _, score, idx in _rfp.extract(
                nq, norm_art, scorer=fuzz.token_sort_ratio,
                limit=10, score_cutoff=FUZZY_THRESHOLD,
            ):
                if idx not in seen_art:
                    candidates.append({"product": products[idx], "score": score, "method": "fuzzy_article"})
                    seen_art.add(idx)

        # 2c. Article query vs DB name (batch) -- catches mislabeled article fields
        if norm_q:
            for _, score, idx in _rfp.extract(
                norm_q, norm_name, scorer=fuzz.partial_ratio,
                limit=5, score_cutoff=FUZZY_THRESHOLD + 10,
            ):
                if idx not in seen_art:
                    candidates.append({"product": products[idx], "score": score, "method": "fuzzy_name_from_article"})

        candidates.sort(key=lambda x: x['score'], reverse=True)

        exact_only = [c for c in candidates if c['score'] >= EXACT_SCORE]
        if exact_only:
            return exact_only[:1]

        if candidates:
            return candidates[:5]

    # ---- 2d. Cyrillic-stripped article match (os segment only) -----------------
    # For lighting databases (e.g. WV 0001.X) where articles are numeric/Latin but
    # PDF specs may include Cyrillic prefixes. Strip Cyrillic from both query and
    # DB articles, then repeat exact + fuzzy search.
    if strip_cyrillic and norm_q_nocyr and len(norm_q_nocyr) >= _NOCYR_MIN_LEN:
        norm_art_nocyr = index.norm_art_nocyr
        seen_nocyr: set = set()
        nocyr_cands: List[Dict] = []

        # 2d-i. Exact lookup in Cyrillic-stripped article index (O(1))
        if norm_q_nocyr in index.art_nocyr_exact:
            for i in index.art_nocyr_exact[norm_q_nocyr]:
                nocyr_cands.append({"product": products[i], "score": EXACT_SCORE, "method": "exact_nocyr"})
                seen_nocyr.add(i)
            return nocyr_cands[:1]

        # Also try brand-stripped variant of nocyr query
        norm_q_nocyr_stripped = _strip_brand_suffix(norm_q_nocyr)
        if norm_q_nocyr_stripped and norm_q_nocyr_stripped in index.art_nocyr_exact:
            for i in index.art_nocyr_exact[norm_q_nocyr_stripped]:
                nocyr_cands.append({"product": products[i], "score": EXACT_SCORE, "method": "exact_nocyr"})
                seen_nocyr.add(i)
            return nocyr_cands[:1]

        # 2d-ii. Substring / fuzzy against Cyrillic-stripped DB articles
        nq = norm_q_nocyr
        for i, na in enumerate(norm_art_nocyr):
            if not na or len(na) < _NOCYR_MIN_LEN:
                continue
            if nq in na or na in nq:
                _len_ratio = min(len(nq), len(na)) / max(len(nq), len(na), 1)
                if _len_ratio >= _CONTAINS_LEN_RATIO:
                    nocyr_cands.append({"product": products[i], "score": CONTAINS_SCORE, "method": "contains_nocyr"})
                    seen_nocyr.add(i)

        for _, score, idx in _rfp.extract(
            nq, norm_art_nocyr, scorer=fuzz.token_sort_ratio,
            limit=10, score_cutoff=FUZZY_THRESHOLD,
        ):
            if idx not in seen_nocyr and len(norm_art_nocyr[idx]) >= _NOCYR_MIN_LEN:
                nocyr_cands.append({"product": products[idx], "score": score, "method": "fuzzy_nocyr"})
                seen_nocyr.add(idx)

        if nocyr_cands:
            nocyr_cands.sort(key=lambda x: x['score'], reverse=True)
            return nocyr_cands[:5]

    # ---- 3. Name-based fallback (batch) ----------------------------------------
    # Very strict: only engage when the name is specific enough (>= _NAME_MIN_LEN chars)
    # and scores are very high. Short/generic names ("Датчик", "Кабель ВВГнг") match
    # dozens of different products -- better to return not_found and let the manager decide.
    if norm_name_q and len(norm_name_q) >= _NAME_MIN_LEN:
        name_cands: List[Dict] = []
        seen_name: set = set()

        # Exact name match (O(1))
        if norm_name_q in index.name_exact:
            for i in index.name_exact[norm_name_q]:
                name_cands.append({"product": products[i], "score": 99, "method": "name_exact"})
                seen_name.add(i)
            name_cands.sort(key=lambda x: x['score'], reverse=True)
            return name_cands[:1]

        # 3a. Substring check on names -- length-ratio guard prevents generic matches
        for i, nn in enumerate(norm_name):
            if not nn:
                continue
            if norm_name_q in nn or nn in norm_name_q:
                _len_ratio = min(len(norm_name_q), len(nn)) / max(len(norm_name_q), len(nn), 1)
                if _len_ratio >= _CONTAINS_LEN_RATIO:
                    name_cands.append({"product": products[i], "score": CONTAINS_SCORE - 2, "method": "name_contains"})
                # Always mark seen even on bad ratio: prevents the short string falling
                # through to partial_ratio which scores 100 for any substring.
                seen_name.add(i)

        # 3b. Batch fuzzy token sort on names
        for _, score, idx in _rfp.extract(
            norm_name_q, norm_name, scorer=fuzz.token_sort_ratio,
            limit=10, score_cutoff=NAME_FUZZY_THRESHOLD,
        ):
            if idx not in seen_name:
                name_cands.append({"product": products[idx], "score": score, "method": "name_fuzzy"})
                seen_name.add(idx)

        # 3c. Batch partial ratio on names (with word-coverage guard)
        for _, score, idx in _rfp.extract(
            norm_name_q, norm_name, scorer=fuzz.partial_ratio,
            limit=10, score_cutoff=NAME_PARTIAL_THRESHOLD,
        ):
            if idx not in seen_name:
                nn = norm_name[idx]
                q_tokens = set(norm_name_q.split())
                n_tokens  = set(nn.split())
                coverage  = len(q_tokens & n_tokens) / max(len(q_tokens), 1)
                if coverage >= _WORD_COVERAGE_MIN:
                    name_cands.append({"product": products[idx], "score": score, "method": "name_partial"})
                    seen_name.add(idx)

        name_cands.sort(key=lambda x: x['score'], reverse=True)
        return name_cands[:5]

    return candidates[:5]


async def match_items(
    pdf_items: List[Dict],
    db: AsyncSession,
    segments: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Find DB candidates for every PDF position.
    Products are fetched once and pre-normalised; exact lookups use O(1) dicts.
    Falls back to name-based search when article search yields no candidates.

    segments: список сегментов для поиска (["ss"] по умолчанию).
              При нескольких сегментах — cross-segment exact дубли → status="multiple".
    """
    if not segments:
        segments = ["ss"]
    search_all = set(segments)

    # Загружаем индекс только для нужных сегментов — не весь каталог
    index = await get_product_index(db, segments=list(search_all))
    logger.info("match_items: %d PDF items vs %d products, segments=%s",
                len(pdf_items), len(index.products), segments)

    results = []

    # Поиск по коду КазНИИСА актуален только для силовых систем (sil).
    # В других сегментах (ss, os) коды КазНИИСА не используются — отключаем.
    _use_kaznisa_code = "sil" in search_all

    # Для сегмента освещения (os) кириллицу в артикулах не учитываем:
    # базы освещения (напр. WV 0001.X "Световые технологии") используют числовые/латинские
    # артикулы, а PDF-спецификации могут добавлять кириллические префиксы/суффиксы.
    _strip_cyrillic = "os" in search_all

    for item in pdf_items:
        all_candidates = find_candidates(
            item.get("article_raw", "") or "",
            index,
            kaznisa_code_raw=(item.get("kaznisa_code_raw", "") or "") if _use_kaznisa_code else "",
            name_raw=item.get("name_raw", "") or "",
            strip_cyrillic=_strip_cyrillic,
        )

        # Фильтруем кандидатов по выбранным сегментам
        candidates = [
            c for c in all_candidates
            if (c["product"].segment or "ss") in search_all
        ]

        if not candidates:
            status       = "not_found"
            best         = None
            cands_data   = []
            match_method = None
        else:
            best_score = candidates[0]['score']
            close      = [c for c in candidates if best_score - c['score'] <= 5]

            if best_score >= EXACT_SCORE:
                # Проверяем cross-segment дубли: одинаковый артикул в разных сегментах
                exact_segs = {(c["product"].segment or "ss") for c in close
                              if c["score"] >= EXACT_SCORE}
                if len(exact_segs) > 1:
                    # Одинаковый артикул найден в нескольких сегментах — требуется выбор
                    status = "multiple"
                    logger.debug(
                        "cross-segment duplicate: article=%r segments=%s",
                        candidates[0]["product"].article, exact_segs
                    )
                else:
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
