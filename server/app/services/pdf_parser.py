"""PDF-specification parser for APS."""
import io
import re
import logging
from typing import List, Dict, Optional, Tuple
import pdfplumber

logger = logging.getLogger(__name__)


def _norm_text(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _norm_for_pattern(text: str) -> str:
    return re.sub(r"[-\s]+", "", text)


def normalize_article(text: str) -> str:
    if not text:
        return ""
    text = text.strip().upper()
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_qty(raw) -> int:
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


HEADER_PATTERNS = {
    "pos": ["поз", "позиция", "№"],
    "name": ["наименование",
             "наим",
             "техническ",
             "обозначениеитехн"],
    "article": ["типмарка",
                "тип,марка",
                "типмарки",
                "маркаобозначение",
                "марка,обозначение",
                "обозначениедок", "обозначение"],
    "code": ["кодоборудования",
             "кодизделия",
             "кодматер",
             "кодобор",
             "шифр",
             "казниис",
             "каз.ниис",
             "кодпродукции"],
    "unit": ["едизм",
             "единиц",
             "ед.изм",
             "едизмерения"],
    "qty": ["кол.",
            "колво",
            "количество",
            "колич"],
}


def _find_column_in_header(row: List, patterns: List[str]) -> Optional[int]:
    for i, cell in enumerate(row):
        norm = _norm_for_pattern(_norm_text(cell))
        if not norm:
            continue
        for pat in patterns:
            if _norm_for_pattern(pat) in norm:
                return i
    return None


def _detect_columns(row: List) -> Optional[Dict[str, int]]:
    full = " ".join(_norm_text(c) for c in row)
    neg = ["маркировка кабел",
           "кабельная трасса",
           "марка кабеля",
           "длина, м",
           "длина м"]
    if any(n in full for n in neg):
        return None
    cols: Dict[str, int] = {}
    for key, patterns in HEADER_PATTERNS.items():
        idx = _find_column_in_header(row, patterns)
        if idx is not None:
            cols[key] = idx
    if "pos" in cols and "article" in cols and "qty" in cols:
        return cols
    return None


def _is_pos_value(cell) -> Optional[str]:
    if cell is None:
        return None
    s = str(cell).strip().rstrip(".")
    if not s:
        return None
    if s.isdigit():
        return s
    if re.match(r"^\d+\.\d+$", s):
        return s
    return None


def _pos_sort_key(pos_str) -> float:
    try:
        return float(pos_str)
    except (ValueError, TypeError):
        return 99999.0


def _is_numbering_row(row: List, cols: Dict[str, int]) -> bool:
    checks = []
    for key in ("article", "name", "qty"):
        idx = cols.get(key)
        if idx is not None and idx < len(row):
            v = _cell(row, idx)
            checks.append(bool(v) and v.isdigit() and len(v) <= 2)
    return len(checks) >= 2 and all(checks)


_KAZNISA_RE = re.compile(r"^\d{3}-\d{3}")

_UNITS = {
    "шт", "шт.", "м", "м.",
    "м2", "м3", "м\xb3",
    "компл", "компл.",
    "рул", "рул.", "кг", "км",
    "л", "уп", "уп.",
    "п.м", "п.м.",
    "пм", "пог.м", "пог.м.",
}

SKIP_KEYWORDS = [
    "оборудование",
    "кабели",
    "провода",
    "монтажные",
    "кабеленесущие",
    "материалы и изделия",
    "комплектующ",
]

# Prefixes that indicate a normative standard reference (ГОСТ, СТ РК, etc.)
# Used only to strip such values from the article field — rows are never skipped.
_STANDARD_PREFIXES = ("гост", "ст рк", "снип", "сп ")

def _strip_standard_article(article: str) -> str:
    """If the article field is a ГОСТ/СТ РК reference, return empty string.

    The row itself is kept — it will be searched by name or kaznisa_code.
    Only the article field is cleared so it does not produce false DB lookups.
    """
    tl = article.strip().lower()
    if not tl:
        return article
    if any(tl.startswith(p) for p in _STANDARD_PREFIXES):
        return ""
    if "гост" in tl or "ст рк" in tl:
        return ""
    return article


def _cell(row: List, idx: Optional[int]) -> str:
    if idx is None or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).replace("\n", " ").strip()


def _get_code(row: List, code_idx: Optional[int]) -> str:
    if code_idx is None:
        return ""
    primary = _cell(row, code_idx)
    if not primary:
        return ""
    cleaned = re.sub(r"(\d)\s+(\d)", r"\1\2", primary)
    if code_idx + 1 < len(row):
        nxt = _cell(row, code_idx + 1)
        nxt = re.sub(r"(\d)\s+(\d)", r"\1\2", nxt)
        if nxt and not _KAZNISA_RE.match(nxt) and re.match(r"^[\d\-]", nxt):
            merged = cleaned + nxt
            if len(re.findall(r"\d+", merged)) > len(re.findall(r"\d+", cleaned)):
                cleaned = merged
    return cleaned.strip()


def extract_specification_from_page(
    table: List[List],
    continuation_cols: Optional[Dict] = None,
) -> Tuple[List[Dict], Optional[Dict]]:
    if not table:
        return [], None
    # Pre-screen: skip tables that are clearly not specification tables
    if _is_non_spec_table(table):
        return [], None

    cols: Optional[Dict[str, int]] = None
    header_row_idx = -1

    for i, row in enumerate(table[:6]):
        detected = _detect_columns(row)
        if detected:
            cols = detected
            header_row_idx = i
            break

    if cols is None:
        cols = _detect_headerless(table)

    if cols is None and continuation_cols is not None:
        max_idx = max(continuation_cols.values()) if continuation_cols else 0
        if table and len(table[0]) > max_idx:
            cols = continuation_cols

    if cols is None:
        return [], None

    data_start = header_row_idx + 1
    if data_start < len(table) and _is_numbering_row(table[data_start], cols):
        data_start += 1

    items: List[Dict] = []
    auto_num = 0

    for row in table[data_start:]:
        if "pos" in cols:
            pos_val = _is_pos_value(_cell(row, cols["pos"]))
            if pos_val is None:
                continue
            pos = pos_val
        else:
            auto_num += 1
            pos = str(auto_num)

        name    = _cell(row, cols.get("name"))
        article = _cell(row, cols.get("article"))
        code    = _get_code(row, cols.get("code"))
        unit    = _cell(row, cols.get("unit"))
        qty     = extract_qty(_cell(row, cols.get("qty")))

        if not name and not article and not code:
            continue

        full_text = (name + " " + article).lower()
        if any(kw in full_text for kw in SKIP_KEYWORDS) and not code:
            continue
        # If the article is a ГОСТ/СТ РК reference — clear it, keep the row
        article = _strip_standard_article(article)

        items.append({
            "pos":              pos,
            "name_raw":         name,
            "article_raw":      normalize_article(article),
            "kaznisa_code_raw": code,
            "unit":             unit or "шт.",
            "qty":              qty,
        })

    # Quality gate: if we relied on continuation_cols and the extracted data
    # looks like garbage (huge quantities, no useful names/articles),
    # discard the items and reset the propagated cols so the bleed stops.
    if continuation_cols is not None and cols is continuation_cols and items:
        high_qty = sum(1 for it in items if it["qty"] > 9999)
        no_content = sum(1 for it in items
                         if not it.get("name_raw") and not it.get("article_raw")
                         and not it.get("kaznisa_code_raw"))
        if high_qty > len(items) * 0.3 or no_content > len(items) * 0.8:
            logger.debug("Discarding %d continuation items (quality gate)", len(items))
            return [], None  # returning None cols resets last_spec_cols

    return items, cols


def _detect_headerless(table: List[List]) -> Optional[Dict[str, int]]:
    sample_text = " ".join(
        str(c or "").lower()
        for row in table[:3]
        for c in row
    )
    neg = ["маркировка кабел",
           "кабельная трасса",
           "марка кабеля"]
    if any(n in sample_text for n in neg):
        return None

    code_votes: Dict[int, int] = {}
    unit_votes: Dict[int, int] = {}

    for row in table[:20]:
        for ci, cell in enumerate(row):
            cv = str(cell or "").replace("\n", " ").strip()
            if _KAZNISA_RE.match(cv):
                code_votes[ci] = code_votes.get(ci, 0) + 1
            cv_low = cv.lower().rstrip(".")
            if cv_low in _UNITS or cv.lower() in _UNITS:
                unit_votes[ci] = unit_votes.get(ci, 0) + 1

    if not code_votes:
        return None

    code_col = max(code_votes, key=lambda k: code_votes[k])
    unit_col = max(unit_votes, key=lambda k: unit_votes[k]) if unit_votes else None

    pos_col  = (code_col - 3) if code_col >= 3 else None
    name_col = (code_col - 2) if code_col >= 2 else None
    art_col  = (code_col - 1) if code_col >= 1 else None
    qty_col  = (unit_col + 1) if unit_col is not None else None

    cols: Dict[str, int] = {"code": code_col}
    if pos_col  is not None: cols["pos"]     = pos_col
    if name_col is not None: cols["name"]    = name_col
    if art_col  is not None: cols["article"] = art_col
    if unit_col is not None: cols["unit"]    = unit_col
    if qty_col  is not None: cols["qty"]     = qty_col

    if "pos" in cols:
        has_pos = any(
            _is_pos_value(_cell(row, cols["pos"])) is not None
            for row in table[:15]
        )
        if not has_pos:
            del cols["pos"]

    return cols


def _is_non_spec_table(table: List[List]) -> bool:
    """Return True for tables that are clearly NOT specification tables.

    Catches: UGO legend tables, cable-routing matrices, symbol reference tables.
    Checked BEFORE any column detection — including continuation_cols.
    """
    if not table:
        return False
    sample = " ".join(str(c or "").lower() for row in table[:4] if row for c in row)
    non_spec_markers = [
        "уго",                          # Legend: условные графические обозначения
        "позиционное обозначение",      # Legend header cell
        "тип линии связи",              # Cable type table
        "граф. обозначение",            # Graphic symbol table
        "маркировка кабел",             # Cable marking table
        "кабельная трасса",             # Cable routing table
        "марка кабеля",                 # Cable brand table
        "структурированные кабельн",    # SCS routing matrix
        "ведомость земляных",           # Earthworks table
    ]
    return any(m in sample for m in non_spec_markers)


def _extract_tables_fast(page) -> list:
    """Extract tables using pdfplumber default settings."""
    try:
        return page.extract_tables() or []
    except Exception:
        return []


def parse_pdf_specification(pdf_bytes: bytes) -> Tuple[List[Dict], str]:
    """Parse entire PDF in a single pass.

    Returns (items, project_name) to avoid opening pdfplumber twice.

    Items are NOT deduplicated by position number because multi-section
    documents (e.g. per-room specs) restart position numbering at 1 for
    every section -- deduplication by pos would discard all but the first
    section.  Items are returned in the order they appear in the document.
    """
    all_items: List[Dict] = []
    last_spec_cols: Optional[Dict] = None
    best_proj_score: float = 0.0
    best_proj_name:  str   = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                tables = _extract_tables_fast(page)
            except Exception as exc:
                logger.warning('Page %d: failed to extract tables: %s', page_num, exc)
                continue

            for table in tables:
                if not table:
                    continue

                # ── Project-name scoring (same pass, no extra PDF open) ──────
                for row in table[:6]:
                    if not row:
                        continue
                    for cell in row:
                        if not cell:
                            continue
                        text = re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()
                        if len(text) >= 20:
                            s = _score_project_name(text)
                            if s > best_proj_score:
                                best_proj_score = s
                                best_proj_name  = text[:500]

                # ── Spec extraction ──────────────────────────────────────────
                items, detected_cols = extract_specification_from_page(
                    table,
                    continuation_cols=last_spec_cols,
                )

                if detected_cols is not None:
                    last_spec_cols = detected_cols

                all_items.extend(items)

    # Renumber positions sequentially across all sections/rooms.
    for idx, item in enumerate(all_items, start=1):
        item["pos"] = str(idx)

    logger.info('Extracted %d positions, project=%r', len(all_items),
                best_proj_name[:60] if best_proj_name else "")
    return all_items, best_proj_name


def _score_project_name(text: str) -> float:
    """Score how likely a text cell is the project name from the title block."""
    score = 0.0
    tl = text.lower()

    # Strong indicators: construction project keywords
    for kw in ["реконструкция", "строительство", "проектирование",
               "капитальный ремонт", "здание", "сооружение", "объект"]:
        if kw in tl:
            score += 10

    # Location indicators typical in project names
    for kw in ["г.", " г ", "область", "район", "ул.", "пл.", "площадь",
               "проспект", "аул", "село", "переулок", "шоссе"]:
        if kw in tl:
            score += 5

    # Ideal length range for a project name
    if 40 <= len(text) <= 300:
        score += 3
    elif len(text) > 300:
        score -= len(text) / 100  # Heavy penalty for very long blobs

    # Quoted text is typical of formal project names
    if '"' in text or "«" in text:
        score += 4

    # Penalise spec table / toc content
    for kw in ["ведомость", "спецификация", "наименование", "ссылочные",
               "указания", "поз.", "лист", "№пп", "кол.", "итого"]:
        if kw in tl:
            score -= 8

    # Penalise if too many sentences (table of contents, general notes, etc.)
    if text.count(".") > 5:
        score -= 4

    # Must contain Cyrillic to qualify at all
    if not re.search(r"[а-яА-ЯёЁ]{3,}", text):
        score = -999

    return score


def extract_project_name(pdf_bytes: bytes) -> str:
    """Extract project name from the title block (угловой штамп) of a PDF.

    Uses a scoring heuristic to pick the most title-like cell across all
    pages: prefers cells with construction/location keywords in the 40-300
    char range; penalises spec-table blobs and long TOC dumps.
    """
    best_score = 0.0
    best_text  = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = []
                try:
                    tables = page.extract_tables() or []
                except Exception:
                        pass
                for table in tables:
                    for row in table[:6]:
                        if not row:
                            continue
                        for cell in row:
                            if not cell:
                                continue
                            text = re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()
                            if len(text) >= 20:
                                s = _score_project_name(text)
                                if s > best_score:
                                    best_score = s
                                    best_text  = text[:500]
    except Exception as exc:
        logger.warning("extract_project_name failed: %s", exc)
    return best_text
