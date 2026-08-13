"""
Разбор прейскуранта КазНИИСА (АГСК) в формате PDF.

Структура ценовой таблицы:
    Код | Наименование | Единица измерения | Класс груза | Масса брутто | Цена

В последней колонке ДВА числа одно под другим:
    верхнее — сметная цена (её и берём),
    нижнее  — отпускная цена (не используется).

После ценового раздела в файле идёт иллюстрированный каталог с колонками
«Код и наименование | Изображение | Описание» — там цен нет, такие страницы
просто не дают строк и пропускаются автоматически.

Разбор потоковый: страницы обрабатываются по одной и сразу освобождаются,
чтобы не удерживать в памяти весь документ.
"""
import logging
import re
from typing import Callable, Dict, Optional

import pdfplumber

logger = logging.getLogger(__name__)

# Код АГСК: 247-201-1504 либо с уточняющим хвостом 541-801-2211-0003
CODE_RE = re.compile(r"^\d{3}-\d{3}-\d{4}(?:-\d{3,4})?$")

# Пробелы-разделители разрядов, встречающиеся в PDF
_SPACES = (" ", " ", " ", " ", " ")


def normalize_code(value: str) -> str:
    """Приводит код к виду без пробелов и переносов."""
    if not value:
        return ""
    s = str(value)
    for sp in _SPACES:
        s = s.replace(sp, "")
    return s.replace("\n", "").strip()


def parse_price(text: str) -> Optional[float]:
    """Сметная цена — верхнее число ячейки.

    '1 158 368\\n1 144 631' → 1158368.0
    Разделители разрядов удаляются, десятичная запятая приводится к точке.
    """
    if not text:
        return None
    first = str(text).split("\n")[0]
    for sp in _SPACES:
        first = first.replace(sp, "")
    first = first.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", first)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_pricelist_pdf(
    path: str,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Dict]:
    """
    Извлекает из прейскуранта {код: {price, name, unit, page}}.

    progress_cb(pct, msg) вызывается по мере разбора.
    При повторе кода оставляется первое вхождение.
    """
    found: Dict[str, Dict] = {}
    dupes = 0

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        logger.info("pricelist: %s — %d страниц", path, total)

        for i, page in enumerate(pdf.pages):
            if progress_cb and (i % 25 == 0 or i == total - 1):
                pct = int(i * 100 / total) if total else 100
                progress_cb(pct, f"Страница {i + 1} из {total}, найдено кодов: {len(found)}")

            try:
                tables = page.extract_tables()
            except Exception as exc:                    # pragma: no cover
                logger.debug("pricelist: страница %d не разобрана: %s", i + 1, exc)
                tables = []

            for tbl in tables or []:
                for row in tbl:
                    if not row or len(row) < 4:
                        continue
                    code = normalize_code(row[0] or "")
                    if not CODE_RE.match(code):
                        continue
                    price = parse_price(row[-1])
                    if price is None:
                        continue        # строка-заголовок группы: код без цены
                    if code in found:
                        dupes += 1
                        continue
                    found[code] = {
                        "price": price,
                        "name": (row[1] or "").replace("\n", " ").strip(),
                        "unit": (row[2] or "").replace("\n", " ").strip(),
                        "page": i + 1,
                    }

            # Освобождаем страницу — иначе pdfplumber держит её разметку в памяти
            page.flush_cache()
            try:
                page.get_textmap.cache_clear()
            except Exception:
                pass

    logger.info("pricelist: разобрано кодов %d (повторов %d)", len(found), dupes)
    if progress_cb:
        progress_cb(100, f"Разбор завершён: {len(found)} кодов")
    return found


def compare_with_products(
    pricelist: Dict[str, Dict],
    products,
    threshold_pct: float = 5.0,
) -> Dict:
    """
    Сверяет цену КазНИИСА товаров с ценой прейскуранта по коду АГСК.

    products — объекты с полями kaznisa_code, kaznisa, article, name, unit,
               brand, segment (подойдут и ORM Product, и ProductRow матчера).

    Возвращает {"rows": [...], "stats": {...}}.
    Знак разницы: плюс — цена в базе выше прейскуранта.
    """
    rows = []
    matched = 0
    no_code = 0
    not_in_pl = 0

    for p in products:
        code = normalize_code(getattr(p, "kaznisa_code", "") or "")
        if not code:
            no_code += 1
            continue
        entry = pricelist.get(code)
        if entry is None:
            not_in_pl += 1
            continue

        try:
            base = float(getattr(p, "kaznisa", None) or 0)
        except (TypeError, ValueError):
            base = 0.0
        price = float(entry["price"])
        if not base or price <= 0:
            continue

        matched += 1
        diff_abs = base - price
        diff_pct = diff_abs / price * 100.0

        u_db = (getattr(p, "unit", "") or "").strip().rstrip(".").lower()
        u_pl = (entry.get("unit", "") or "").strip().rstrip(".").lower()

        rows.append({
            "code":       code,
            "article":    getattr(p, "article", "") or "",
            "name_db":    getattr(p, "name", "") or "",
            "name_pl":    entry.get("name", ""),
            "brand":      getattr(p, "brand", "") or "",
            "segment":    getattr(p, "segment", "") or "",
            "unit_db":    getattr(p, "unit", "") or "",
            "unit_pl":    entry.get("unit", ""),
            "same_unit":  u_db == u_pl,
            "price_db":   base,
            "price_pl":   price,
            "diff_abs":   diff_abs,
            "diff_pct":   diff_pct,
            "over":       abs(diff_pct) > threshold_pct,
            "page":       entry.get("page"),
        })

    rows.sort(key=lambda r: -abs(r["diff_pct"]))
    over = [r for r in rows if r["over"]]

    stats = {
        "pricelist_codes": len(pricelist),
        "products_total":  no_code + not_in_pl + matched,
        "without_code":    no_code,
        "not_in_pricelist": not_in_pl,
        "matched":         matched,
        "over_threshold":  len(over),
        "over_higher":     sum(1 for r in over if r["diff_abs"] > 0),
        "over_lower":      sum(1 for r in over if r["diff_abs"] < 0),
        "unit_mismatch":   sum(1 for r in over if not r["same_unit"]),
        "within":          matched - len(over),
        "threshold_pct":   threshold_pct,
    }
    return {"rows": rows, "stats": stats}
