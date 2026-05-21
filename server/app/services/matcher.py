from rapidfuzz import fuzz, process
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.models.models import Product
from typing import List, Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)

EXACT_SCORE    = 100
CONTAINS_SCORE = 95
FUZZY_THRESHOLD = 68   # минимальный % для нечёткого совпадения


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.upper().strip()
    t = re.sub(r'[–—−]', '-', t)
    t = re.sub(r'\s+', ' ', t)
    # убираем версии типа W1.02, W2.02 для более широкого поиска
    t_no_ver = re.sub(r'\s+W\d+\.\d+$', '', t)
    return t_no_ver.strip()


async def get_all_products(db: AsyncSession) -> List[Product]:
    result = await db.execute(
        select(Product).where(Product.is_active == True)
    )
    return result.scalars().all()


def product_to_dict(p: Product) -> Dict:
    return {
        "id":           p.id,
        "article":      p.article or "",
        "name":         p.name or "",
        "unit":         p.unit or "шт.",
        "brand":        p.brand or "",
        "kaznisa":      p.kaznisa,
        "rrts":         p.rrts,
        "mrc":          p.mrc,
        "opt":          p.opt,
        "partner":      p.partner,
        "multiplicity": p.multiplicity,
        "kaznisa_code": p.kaznisa_code or "",
    }


def find_candidates(article_raw: str, all_products: List[Product], kaznisa_code_raw: str = "") -> List[Dict]:
    """
    Возвращает список кандидатов с оценкой схожести.
    Первый — лучший. Если score >= 95 и один — точное совпадение.
    Если несколько с близкими score — «несколько вариантов».
    """
    norm_q    = normalize(article_raw)
    norm_code = normalize(kaznisa_code_raw)

    if not norm_q and not norm_code:
        return []

    candidates = []

    for p in all_products:
        norm_art  = normalize(p.article     or "")
        norm_name = normalize(p.name        or "")
        norm_pkaz = normalize(p.kaznisa_code or "")

        # 1. Точное совпадение артикула → 100
        if norm_q and norm_art == norm_q:
            candidates.append({"product": p, "score": EXACT_SCORE, "method": "exact"})
            continue

        # 2. Точное совпадение кода оборудования → 98
        #    (код из PDF == kaznisa_code в БД)
        if norm_code and norm_pkaz and norm_pkaz == norm_code:
            candidates.append({"product": p, "score": 98, "method": "code_exact"})
            continue

        # 3. Вхождение артикула (один содержит другой) → 95
        if norm_q and norm_art and (norm_q in norm_art or norm_art in norm_q):
            candidates.append({"product": p, "score": CONTAINS_SCORE, "method": "contains"})
            continue

        # 4. Вхождение кода (код из PDF входит в kaznisa_code или наоборот) → 90
        if norm_code and norm_pkaz and (norm_code in norm_pkaz or norm_pkaz in norm_code):
            candidates.append({"product": p, "score": 90, "method": "code_contains"})
            continue

        # 5. Нечёткий по артикулу
        if norm_q:
            score_art = fuzz.token_sort_ratio(norm_q, norm_art)
            if score_art >= FUZZY_THRESHOLD:
                candidates.append({"product": p, "score": score_art, "method": "fuzzy_article"})
                continue

        # 6. Нечёткий по наименованию
        if norm_q:
            score_name = fuzz.partial_ratio(norm_q, norm_name)
            if score_name >= FUZZY_THRESHOLD + 10:
                candidates.append({"product": p, "score": score_name, "method": "fuzzy_name"})
                continue

        # 7. Нечёткий по коду оборудования (если артикул пуст или не дал результата)
        if norm_code and norm_pkaz and not norm_q:
            score_code = fuzz.token_sort_ratio(norm_code, norm_pkaz)
            if score_code >= FUZZY_THRESHOLD:
                candidates.append({"product": p, "score": score_code, "method": "fuzzy_code"})

    # Сортируем по убыванию score
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Если есть точное совпадение (score=100) — возвращаем ТОЛЬКО его.
    # Не показываем «частичные» рядом, потому что точное всегда правильнее.
    exact_only = [c for c in candidates if c["score"] >= EXACT_SCORE]
    if exact_only:
        return exact_only[:1]

    # Иначе — топ-5 кандидатов
    return candidates[:5]


async def match_items(
    pdf_items: List[Dict],
    db: AsyncSession,
) -> List[Dict]:
    """
    Для каждой позиции из PDF находит кандидатов в БД.
    Статус:
      'exact'    — одно точное совпадение (зелёный)
      'multiple' — несколько вариантов (жёлтый)
      'fuzzy'    — одно нечёткое (жёлтый)
      'not_found'— не найдено (красный)
    """
    all_products = await get_all_products(db)
    results = []

    for item in pdf_items:
        candidates = find_candidates(
            item["article_raw"],
            all_products,
            kaznisa_code_raw=item.get("kaznisa_code_raw", "") or "",
        )

        if not candidates:
            status = "not_found"
            best = None
            cands_data = []
        else:
            best_score = candidates[0]["score"]

            # Несколько кандидатов с близкими оценками (разница ≤ 5)
            close = [c for c in candidates if best_score - c["score"] <= 5]

            if best_score >= EXACT_SCORE:
                status = "exact"
            elif len(close) > 1:
                status = "multiple"
            else:
                status = "fuzzy"

            best = product_to_dict(candidates[0]["product"])
            cands_data = [
                {**product_to_dict(c["product"]), "score": c["score"], "method": c["method"]}
                for c in candidates
            ]

        results.append({
            **item,
            "status":     status,          # exact / multiple / fuzzy / not_found
            "best_match": best,            # лучший кандидат или None
            "candidates": cands_data,      # все кандидаты (для выбора пользователем)
        })

    return results
