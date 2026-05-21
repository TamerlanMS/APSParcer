"""
Парсер PDF-спецификации АПС.

Особенность: разные проектировщики выпускают спецификации с очень разной
шириной таблицы (от 9 до 21 колонок). pdfplumber возвращает все вертикальные
линии как отдельные столбцы, поэтому жёсткий маппинг «Поз = col 0, Артикул = col 2»
не работает.

Стратегия — находим строку-заголовок (содержит «Поз», «Наименование», «Тип»,
«Кол», «Ед» и т.п.) и запоминаем индексы её колонок. Дальше используем их для
строк данных. Если заголовок не найден — fallback на старую логику.
"""
import io
import re
import logging
from typing import List, Dict, Optional, Tuple
import pdfplumber

logger = logging.getLogger(__name__)


# ── Утилиты ────────────────────────────────────────────────────────────────────

def _norm_text(v) -> str:
    """Нормализация ячейки: убираем переносы строк, склейка пробелов, lowercase."""
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def normalize_article(text: str) -> str:
    """Нормализация артикула для поиска"""
    if not text:
        return ""
    text = text.strip().upper()
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_qty(raw) -> int:
    """Первое целое число из строки количества."""
    if raw is None:
        return 1
    s = str(raw).strip().replace("\xa0", " ")
    if not s:
        return 1
    m = re.search(r"\d[\d ]*", s)
    if not m:
        return 1
    num = re.sub(r"\s+", "", m.group(0))
    try:
        return int(num)
    except ValueError:
        return 1


# ── Определение колонок ───────────────────────────────────────────────────────

# Ключевые слова для распознавания заголовков колонок таблицы спецификации.
HEADER_PATTERNS = {
    "pos":     ["поз", "позиция", "№"],
    "name":    ["наименование", "наим.", "техническ", "обозначение и техн"],
    "article": ["тип, марка", "тип марка", "марка", "обозначение док"],
    "code":    ["код оборудования", "код изделия", "код матери", "код обор",
                "шифр", "каз ниис", "казниис"],
    "unit":    ["ед. изм", "ед.изм", "единиц", "ед "],
    "qty":     ["кол.", "кол-во", "колич"],
}


def _find_column_in_header(row: List[str], patterns: List[str]) -> Optional[int]:
    """Возвращает индекс колонки в строке-заголовке, чей текст содержит один из patterns."""
    for i, cell in enumerate(row):
        norm = _norm_text(cell)
        if not norm:
            continue
        for pat in patterns:
            if pat in norm:
                return i
    return None


def _detect_columns(row: List[str]) -> Optional[Dict[str, int]]:
    """Пытается определить, является ли строка заголовком таблицы спецификации.
    Возвращает словарь {pos: idx, name: idx, article: idx, qty: idx, unit: idx}
    или None, если не похоже на заголовок."""
    # Отрицательные сигналы — это таблица кабельной разводки/трасс, а не оборудования
    full = " ".join(_norm_text(c) for c in row)
    if any(neg in full for neg in ["маркировка кабел", "кабельная трасса", "марка кабеля",
                                    "длина, м", "длина м"]):
        return None

    cols = {}
    for key, patterns in HEADER_PATTERNS.items():
        idx = _find_column_in_header(row, patterns)
        if idx is not None:
            cols[key] = idx
    # Жёсткое требование: таблица спецификации обязательно содержит
    # «Поз», «Артикул/Тип, марка» и «Количество». Это отсекает таблицы
    # сигналов АВУ, кабельных трасс и описательные таблички.
    if "pos" in cols and "article" in cols and "qty" in cols:
        return cols
    return None


def _is_pos_value(cell) -> Optional[int]:
    """Если ячейка содержит чистое число — возвращает его, иначе None.
    Допускает «1.», «12»."""
    if cell is None:
        return None
    s = str(cell).strip().rstrip(".")
    if s.isdigit():
        return int(s)
    return None


# ── Парсинг таблиц ────────────────────────────────────────────────────────────

SKIP_KEYWORDS = ["оборудование", "кабели", "провода", "монтажные", "кабеленесущие",
                 "материалы и изделия", "комплектующ"]


def _cell(row: List, idx: Optional[int]) -> str:
    if idx is None or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).replace("\n", " ").strip()


def extract_specification_from_page(table: List[List]) -> List[Dict]:
    """Извлекает позиции из одной таблицы pdfplumber'а."""
    if not table or len(table) < 2:
        return []

    # 1) Пробуем найти строку-заголовок
    cols = None
    header_row_idx = -1
    for ri, row in enumerate(table[:6]):  # заголовок в первых 6 строках таблицы
        detected = _detect_columns(row)
        if detected:
            cols = detected
            header_row_idx = ri
            break

    # 2) Если заголовок не нашли — пропускаем таблицу. Не угадываем колонки,
    # чтобы не схватывать таблицы кабельных трасс, сигналов АВУ и т.п.
    if not cols:
        return []

    items = []
    seen_pos_in_table = set()  # дедуп внутри одной таблицы — каждая поз. уникальна
    for ri, row in enumerate(table):
        if ri <= header_row_idx:
            continue
        if not row:
            continue

        # Достаём поля
        pos_val = _cell(row, cols.get("pos"))
        pos_int = _is_pos_value(pos_val)
        if pos_int is None:
            continue  # строки без числовой позиции — пропускаем
        if pos_int in seen_pos_in_table:
            continue  # повтор той же позиции (продолжение описания на след. строке)
        seen_pos_in_table.add(pos_int)

        name_raw    = _cell(row, cols.get("name"))
        article_raw = _cell(row, cols.get("article"))
        code_raw    = _cell(row, cols.get("code"))
        qty_raw     = _cell(row, cols.get("qty"))

        # Если артикул пустой — возможно, он в наименовании или строка-разделитель
        if not article_raw or article_raw in ("-", "—"):
            # Иногда артикул сразу в name (мелкие таблицы)
            if not name_raw:
                continue
            article_raw = name_raw

        # Фильтр служебных строк-разделителей
        nm_low = name_raw.lower()
        if any(k in nm_low for k in SKIP_KEYWORDS) and not article_raw:
            continue

        # Количество — если в основной колонке qty пусто, пробуем соседние
        if not re.search(r"\d", qty_raw):
            for alt_idx in [cols.get("qty"), cols.get("qty", -1) + 1 if cols.get("qty") is not None else None,
                            cols.get("qty", -1) - 1 if cols.get("qty") is not None else None]:
                if alt_idx is None or alt_idx < 0 or alt_idx >= len(row):
                    continue
                val = str(row[alt_idx] or "").strip()
                if re.search(r"\d", val):
                    cand = extract_qty(val)
                    if cand != pos_int:
                        qty_raw = val
                        break

        items.append({
            "pos":              pos_int,
            "name":             name_raw,
            "article_raw":      article_raw,
            "kaznisa_code_raw": code_raw,   # «Код оборудования/изделия/материала» из PDF
            "qty":              extract_qty(qty_raw),
        })

    return items


# ── Главная функция ──────────────────────────────────────────────────────────

def parse_pdf_specification(pdf_bytes: bytes) -> List[Dict]:
    """
    Парсит PDF и возвращает список позиций.
    Спецификация обычно в конце документа, но проверяем все страницы.
    """
    items = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # Сначала — таблицы по линиям. Если они дали хоть одну позицию,
                # «text»-стратегию не запускаем, чтобы не получить дубли.
                page_items = []
                try:
                    tables = page.extract_tables({
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 5,
                    }) or []
                    for table in tables:
                        page_items.extend(extract_specification_from_page(table))
                except Exception as e:
                    logger.debug(f"extract_tables(lines) fail page {page_num}: {e}")


                if not page_items:
                    # Запасной вариант — стратегия «text», для таблиц без линий
                    try:
                        tables = page.extract_tables({
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "snap_tolerance": 4,
                        }) or []
                        for table in tables:
                            page_items.extend(extract_specification_from_page(table))
                    except Exception as e:
                        logger.debug(f"extract_tables(text) fail page {page_num}: {e}")

                items.extend(page_items)
    except Exception as e:
        logger.error(f"PDF parsing error: {e}", exc_info=True)
        raise ValueError(f"Ошибка парсинга PDF: {e}")

    # Дедуп по (pos, article_raw)
    seen = set()
    unique = []
    for it in items:
        key = (it["pos"], it["article_raw"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)

    logger.info(f"Extracted {len(unique)} positions from PDF")
    return sorted(unique, key=lambda x: x["pos"])
