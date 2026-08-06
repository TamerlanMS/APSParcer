"""
Запись результатов подбора обратно в исходный файл спецификации.

Подбор пишется в ту же строку, из которой позиция была прочитана
(номер строки приходит с сервера в поле `row`). Значения кладутся в
соответствующие колонки исходной шапки:

    Тип, марка, обозначение   ← артикул подобранного товара
    Код продукции             ← код АГСК из базы
    Поставщик                 ← бренд из базы
    Наименование              ← наименование из базы (только при полной замене)

Полная замена строки выполняется, когда менеджер подобрал ИНУЮ позицию
(аналог): артикул из базы отличается от исходного. В этом случае
перезаписывается и наименование, а в «Примечание» добавляется пометка
с исходным артикулом, чтобы проектировщик видел, что было заменено.

Форматирование, объединения, ширины колонок и прочие листы файла не трогаются:
openpyxl открывает книгу и сохраняет её обратно, меняются только значения ячеек.
"""
import logging
import os
import re
import shutil
from typing import Dict, List, Optional

import openpyxl

logger = logging.getLogger(__name__)


# Те же шаблоны заголовков, что и в серверном парсере
_COL_PATTERNS = [
    ("pos",     ("поз",)),
    ("name",    ("наименование", "техническая характеристика", "наимен")),
    ("article", ("тип", "марка", "обозначение")),
    ("code",    ("код продукции", "код")),
    ("brand",   ("поставщик", "изготовитель", "производитель", "бренд")),
    ("unit",    ("ед. изме", "ед.изм", "единица", "ед изм")),
    ("qty",     ("кол-во", "количество", "коли-чест")),
    ("mass",    ("масса",)),
    ("note",    ("примечание", "приме-чание")),
]

_MAX_HEADER_SCAN = 30
_MIN_HEADER_HITS = 3

_REPLACED_TAG = "Заменено при подборе"


def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


def _detect_header(ws, max_col: int):
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


def _fallback_map(max_col: int) -> Dict[str, int]:
    order = ["pos", "name", "article", "code", "brand", "unit", "qty", "mass", "note"]
    return {k: i + 1 for i, k in enumerate(order) if i + 1 <= max_col}


def _set(ws, row: int, col_map: Dict[str, int], key: str, value) -> bool:
    """Пишет значение в ячейку, если колонка известна и значение непустое."""
    c = col_map.get(key)
    if not c or value in (None, ""):
        return False
    ws.cell(row=row, column=c).value = value
    return True


def write_selection_to_spec(path: str,
                            items: List[Dict],
                            sheet_name: Optional[str] = None,
                            backup: bool = False) -> int:
    """
    Записывает подобранные позиции в исходный файл спецификации.

    path       — путь к файлу спецификации (перезаписывается на месте);
    items      — позиции со страницы предпросмотра (нужны поля row/best_match);
    sheet_name — лист спецификации; если не задан, берётся первый;
    backup     — сделать копию «<имя>.bak.xlsx» перед перезаписью.
                 По умолчанию выключено: копия засоряет папку менеджера.
                 Запись идёт через временный файл, поэтому при сбое исходник
                 остаётся нетронутым и без резервной копии.

    Возвращает количество записанных строк.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Файл спецификации не найден: {path}")

    if backup:
        base, ext = os.path.splitext(path)
        bak = f"{base}.bak{ext or '.xlsx'}"
        try:
            shutil.copyfile(path, bak)
        except OSError as exc:
            logger.warning("spec_writer: не удалось создать резервную копию: %s", exc)

    wb = openpyxl.load_workbook(path)
    ws = (wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames
          else wb[wb.sheetnames[0]])

    max_col = min(ws.max_column or 1, 30)
    header_row, col_map = _detect_header(ws, max_col)
    if not col_map:
        col_map = _fallback_map(max_col)
        logger.warning("spec_writer: шапка не распознана, позиционная раскладка")

    written = 0
    for it in items:
        if it.get("is_heading"):
            continue
        row = it.get("row")
        bm  = it.get("best_match") or {}
        if not row or not bm:
            continue
        # Строки не с этого листа пропускаем
        if it.get("sheet") and sheet_name and it["sheet"] != sheet_name:
            continue

        db_article = _norm(bm.get("article"))
        src_article = _norm(it.get("article_raw"))
        # Полная замена, если подобрана иная позиция (аналог)
        is_replacement = bool(db_article and src_article
                              and db_article.lower() != src_article.lower())

        touched = False
        touched |= _set(ws, row, col_map, "article", db_article)
        touched |= _set(ws, row, col_map, "code",
                        _norm(bm.get("kaznisa_code")) or None)
        touched |= _set(ws, row, col_map, "brand", _norm(bm.get("brand")) or None)

        if is_replacement:
            # Заменяем наименование и единицу на данные из базы
            touched |= _set(ws, row, col_map, "name", _norm(bm.get("name")) or None)
            touched |= _set(ws, row, col_map, "unit", _norm(bm.get("unit")) or None)

            note_col = col_map.get("note")
            if note_col:
                cur = _norm(ws.cell(row=row, column=note_col).value)
                mark = f"{_REPLACED_TAG}: было {src_article}"
                if _REPLACED_TAG not in cur:
                    ws.cell(row=row, column=note_col).value = (
                        f"{cur}; {mark}" if cur else mark
                    )

        # Количество — если менеджер правил его в предпросмотре
        qty = it.get("qty")
        if qty and col_map.get("qty"):
            try:
                q = float(qty)
                ws.cell(row=row, column=col_map["qty"]).value = (
                    int(q) if q.is_integer() else q
                )
                touched = True
            except (TypeError, ValueError):
                pass

        if touched:
            written += 1

    # Пишем во временный файл рядом с исходным и подменяем его атомарно:
    # при сбое (нет места, файл открыт в Excel) оригинал остаётся целым.
    tmp_path = f"{path}.tmp"
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.info("spec_writer: записано %d строк в %s (лист %s)",
                written, path, ws.title)
    return written
