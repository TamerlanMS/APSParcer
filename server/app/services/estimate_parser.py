"""
Разбор сметного документа генподрядчика (локальная смета, Excel).

Учитываются только листы с метками в названии: Q9, G9, K9 и РС.
Прочие листы — обложки, сводные расчёты — пропускаются.

Структура листа (НДЦС РК, форма 4), шапка обычно в районе 18-й строки:

    Номер по порядку | Шифр позиции норматива | Наименование работ и затрат |
    Единица измерения | Количество | Стоимость единицы измерения | Общая стоимость

Особенности формата:
  • Позиция верхнего уровня — целое число в первой колонке (1, 2, 3...).
    Строки вида 1.1, 8.2.1 — это расшифровка затрат внутри позиции
    (труд рабочих, машины, материалы), в выборку они не идут.
  • В «Шифре» зашит код АГСК: «248-303-0234 ПрСЦ 11.2025»,
    «541-801-1605-0007 ПрСЦ 11.2025». По нему смета связывается со спецификацией.
  • Коды норм РСНБ («1310-0701-0207») имеют другой формат (4-4-4) и под
    шаблон кода АГСК не подходят — то есть нормы работ отсеиваются сами.
    При этом оборудование, расценённое по РСНБ («248-301-0914 РСНБ РК 2022»),
    распознаётся штатно — у него код в формате АГСК.
  • Строки-итоги («ВСЕГО ПО СМЕТЕ», «Раздел 1.», «из них:») номера не имеют
    и потому тоже отсеиваются.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

import openpyxl

logger = logging.getLogger(__name__)

# Метки листов, которые нужно обрабатывать.
# Латинские и кириллические буквы здесь выглядят одинаково, а в названиях
# листов встречаются оба написания — перечислены оба, чтобы разбор не
# зависел от того, какую раскладку выбрал составитель сметы.
SHEET_MARKERS = (
    "Q9",
    "G9",
    "K9", "К9",      # латинская K и кириллическая К
    "РС", "PC",      # кириллические Р С и латинские P C
)

# Код АГСК внутри шифра позиции: 248-303-0234 либо 541-801-1605-0007
CODE_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4}(?:-\d{3,4})?)\b")

# Номер позиции верхнего уровня — только целое число
TOP_LEVEL_RE = re.compile(r"^\d+$")

# Сметные цены в локальной смете идут без НДС, наши цены КП — с ним.
# Без приведения к общей базе смета всегда оказывалась дешевле на 16 %.
ESTIMATE_VAT = 1.16

_MAX_HEADER_SCAN = 40
_MIN_HEADER_HITS = 4

_COL_PATTERNS: List[Tuple[str, Tuple[str, ...]]] = [
    ("num",   ("номер по порядку", "№ п/п", "номер")),
    ("ref",   ("шифр",)),
    ("name",  ("наименование",)),
    ("unit",  ("единица", "ед. изм", "ед.изм")),
    ("qty",   ("количество", "кол-во")),
    ("price", ("стоимость единицы", "цена единицы", "стоимость ед")),
    ("total", ("общая стоимость", "всего", "сумма")),
]


def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


def _num(v) -> Optional[float]:
    """Число из ячейки: принимает 12, «12,5», «1 234.50»; мусор → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f
    s = _norm(v)
    for sp in (" ", " ", " ", " "):
        s = s.replace(sp, "")
    s = s.replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def is_estimate_sheet(name: str) -> bool:
    """True — лист участвует в разборе (есть метка Q9, G9, K9 или РС)."""
    n = (name or "").upper()
    return any(mark.upper() in n for mark in SHEET_MARKERS)


def _detect_header(ws) -> Tuple[Optional[int], Dict[str, int]]:
    """Ищет строку шапки и раскладку колонок."""
    max_col = min(ws.max_column or 1, 20)
    best_row, best_map, best_hits = None, {}, 0

    for r in range(1, min(ws.max_row, _MAX_HEADER_SCAN) + 1):
        cells = {c: _norm(ws.cell(row=r, column=c).value).lower()
                 for c in range(1, max_col + 1)}
        if not any(cells.values()):
            continue

        col_map: Dict[str, int] = {}
        for key, patterns in _COL_PATTERNS:
            if key in col_map:
                continue
            for c, text in cells.items():
                if not text or c in col_map.values():
                    continue
                if any(p in text for p in patterns):
                    col_map[key] = c
                    break

        if len(col_map) > best_hits:
            best_row, best_map, best_hits = r, col_map, len(col_map)

    if best_hits < _MIN_HEADER_HITS:
        return None, {}
    return best_row, best_map


def _fallback_map() -> Dict[str, int]:
    """Раскладка формы 4, если шапку распознать не удалось."""
    return {"num": 1, "ref": 2, "name": 3, "unit": 4,
            "qty": 5, "price": 6, "total": 7}


def parse_estimate_excel(path: str) -> Dict:
    """
    Разбирает смету и возвращает:

        {
          "items":  [ {code, name, unit, qty, price, total, sheet, row, ref}, ... ],
          "sheets": [ обработанные листы ],
          "skipped_sheets": [ пропущенные листы ],
          "stats": {...}
        }

    price — сметная цена за единицу, total — общая стоимость из сметы.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)

    items: List[Dict] = []
    used, skipped = [], []

    for sheet_name in wb.sheetnames:
        if not is_estimate_sheet(sheet_name):
            skipped.append(sheet_name)
            continue

        ws = wb[sheet_name]
        header_row, col_map = _detect_header(ws)
        if not col_map:
            header_row, col_map = 18, _fallback_map()
            logger.warning("estimate: шапка не распознана на листе %s, "
                           "использую раскладку формы 4", sheet_name)

        def cell(r: int, key: str):
            c = col_map.get(key)
            return ws.cell(row=r, column=c).value if c else None

        found = 0
        for r in range((header_row or 1) + 1, (ws.max_row or 0) + 1):
            num = _norm(cell(r, "num"))
            if not TOP_LEVEL_RE.match(num):
                continue        # подстрока расшифровки затрат либо итог

            name = _norm(cell(r, "name"))
            ref  = _norm(cell(r, "ref"))
            if not name:
                continue
            # Сразу под шапкой идёт строка нумерации колонок «1 2 3 4 5 6 7» —
            # у неё в «наименовании» просто цифра
            if name.isdigit():
                continue

            price = _num(cell(r, "price"))
            if price is None or price <= 0:
                continue        # без цены позиция бесполезна

            m = CODE_RE.search(ref)
            code = m.group(1) if m else ""

            items.append({
                "code":  code,
                "ref":   ref,
                "name":  name,
                "unit":  _norm(cell(r, "unit")),
                "qty":   _num(cell(r, "qty")) or 0.0,
                "price": price,
                "total": _num(cell(r, "total")) or 0.0,
                "sheet": sheet_name,
                "row":   r,
            })
            found += 1

        used.append(sheet_name)
        logger.info("estimate: лист %s — позиций %d", sheet_name, found)

    with_code = sum(1 for i in items if i["code"])
    logger.info("estimate: %s — листов %d, позиций %d (с кодом АГСК %d)",
                path, len(used), len(items), with_code)

    return {
        "items":  items,
        "sheets": used,
        "skipped_sheets": skipped,
        "stats": {
            "sheets_used":    len(used),
            "sheets_skipped": len(skipped),
            "items":          len(items),
            "with_code":      with_code,
        },
    }


# ─── Сопоставление сметы с позициями спецификации ────────────────────────────

def _norm_key(s: str) -> str:
    """Нормализует строку для сравнения: нижний регистр, только буквы и цифры."""
    return re.sub(r"[^0-9a-zа-яё]+", "", (s or "").lower())


def _name_tokens(s: str) -> set:
    """Значимые слова наименования для нечёткого сравнения."""
    words = re.findall(r"[0-9a-zа-яё]{3,}", (s or "").lower())
    return set(words)


def match_estimate(items: List[Dict], estimate_items: List[Dict],
                   min_name_score: float = 0.6) -> Dict:
    """
    Проставляет позициям спецификации сметную цену с НДС.

    Порядок поиска (первое сработавшее и берём):
      1. код АГСК — точное совпадение;
      2. артикул — если он встречается в шифре или наименовании сметы;
      3. наименование — по доле общих значимых слов, не ниже min_name_score.

    Цена из сметы умножается на ESTIMATE_VAT, иначе она сравнивалась бы
    с нашей ценой КП, где НДС уже заложен.

    items изменяются на месте: добавляются estimate_price (с НДС),
    estimate_price_net (как в смете), estimate_match (способ связи)
    и estimate_name (что нашли в смете).
    Возвращает статистику сопоставления.
    """
    by_code: Dict[str, Dict] = {}
    for e in estimate_items:
        c = (e.get("code") or "").strip()
        if c and c not in by_code:
            by_code[c] = e

    # Индексы для поиска по артикулу и наименованию
    est_text = [(e, _norm_key(e.get("ref", "") + " " + e.get("name", "")),
                 _name_tokens(e.get("name", ""))) for e in estimate_items]

    stats = {"by_code": 0, "by_article": 0, "by_name": 0, "unmatched": 0,
             "total": 0}

    for it in items:
        if it.get("is_heading"):
            continue
        stats["total"] += 1

        bm = it.get("best_match") or {}
        code = (bm.get("kaznisa_code") or it.get("kaznisa_code_raw") or "").strip()
        art  = (bm.get("article") or it.get("article_raw") or "").strip()
        name = (bm.get("name") or it.get("name_raw") or "").strip()

        hit, how = None, ""

        # 1. Код АГСК
        if code and code in by_code:
            hit, how = by_code[code], "code"

        # 2. Артикул внутри шифра или наименования сметы
        if hit is None and len(art) >= 4:
            art_key = _norm_key(art)
            if art_key:
                for e, text, _tok in est_text:
                    if art_key in text:
                        hit, how = e, "article"
                        break

        # 3. Наименование — по доле общих слов
        if hit is None and name:
            tokens = _name_tokens(name)
            if tokens:
                best, best_score = None, 0.0
                for e, _text, etok in est_text:
                    if not etok:
                        continue
                    common = len(tokens & etok)
                    if not common:
                        continue
                    score = common / min(len(tokens), len(etok))
                    if score > best_score:
                        best, best_score = e, score
                if best is not None and best_score >= min_name_score:
                    hit, how = best, "name"

        if hit is None:
            stats["unmatched"] += 1
            continue

        _net = float(hit.get("price") or 0)
        it["estimate_price_net"] = _net
        it["estimate_price"]     = round(_net * ESTIMATE_VAT, 2)
        it["estimate_match"] = how
        it["estimate_name"]  = hit.get("name", "")
        stats[f"by_{how}"] += 1

    stats["vat"] = ESTIMATE_VAT
    logger.info("estimate match: всего %d, по коду %d, по артикулу %d, "
                "по наименованию %d, не найдено %d, НДС ×%s",
                stats["total"], stats["by_code"], stats["by_article"],
                stats["by_name"], stats["unmatched"], ESTIMATE_VAT)
    return stats
