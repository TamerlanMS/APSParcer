"""PDF-specification parser for APS."""
import base64
import collections
import io
import json
import os
import re
import logging
import threading
import time
from typing import List, Dict, Optional, Tuple
import pdfplumber

try:
    import fitz as _fitz  # PyMuPDF — fast text extraction for Phase 1
    _FITZ_AVAILABLE = True
except ImportError:
    _fitz = None
    _FITZ_AVAILABLE = False

try:
    import pytesseract as _tesseract
    from pytesseract import Output as _TsrOutput
    from PIL import Image as _PIL_Image
    _TESSERACT_AVAILABLE = True
except ImportError:
    _tesseract = None
    _TsrOutput = None
    _PIL_Image = None
    _TESSERACT_AVAILABLE = False

logger = logging.getLogger(__name__)

# OCR DPI: 150 balances accuracy vs. speed for A4 spec sheets (200 is too slow)
_OCR_DPI = 150
# Minimum Tesseract confidence to accept a word (0-100)
_OCR_MIN_CONF = 25
# Horizontal gap (px at _OCR_DPI) that separates adjacent table columns
_OCR_COL_GAP = 22
# Tesseract timeout per page in seconds (0 = no limit — dangerous)
_OCR_PAGE_TIMEOUT = 45
# Cached Tesseract language string — computed once on first OCR call
_OCR_LANG_CACHE: Optional[str] = None

# GPT-4o-mini Vision OCR — preferred over Tesseract when API key is set
_VISION_DPI = 100   # 100 DPI = 827x1169px on A4 — detail=high → 4-6 tiles ≈ 1000 tokens/page
_OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")


# ── OCR helpers ─────────────────────────────────────────────────────────────

def _get_ocr_lang() -> str:
    """Return Tesseract language string, computed once and cached."""
    global _OCR_LANG_CACHE
    if _OCR_LANG_CACHE is not None:
        return _OCR_LANG_CACHE
    try:
        langs = _tesseract.get_languages()
        lang_str = "+".join(l for l in ("rus", "kaz", "eng") if l in langs)
        if not lang_str:
            lang_str = "eng"
    except Exception:
        lang_str = "rus+eng"
    _OCR_LANG_CACHE = lang_str
    logger.info("OCR: Tesseract language pack: %s", lang_str)
    return lang_str


def _is_scanned_pdf(pdf_bytes: bytes) -> bool:
    """Return True when the first 5 pages have no extractable text."""
    try:
        if _FITZ_AVAILABLE and _fitz is not None:
            doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
            n = min(5, len(doc))
            for i in range(n):
                try:
                    txt = doc[i].get_text() or ""
                except Exception:
                    txt = ""
                if len(txt.strip()) > 30:
                    doc.close()
                    return False
            doc.close()
            return True
        # Fallback: pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:5]:
                txt = page.extract_text() or ""
                if len(txt.strip()) > 30:
                    return False
        return True
    except Exception:
        return False


def _ocr_page_to_table(pix, dpi: int = _OCR_DPI) -> List[List[str]]:
    """OCR a PyMuPDF Pixmap and reconstruct a pseudo-table.

    Strategy:
      1. Run pytesseract image_to_data to get per-word bounding boxes.
      2. Group words into visual rows by vertical proximity (±15 px).
      3. Within each row, split into cells wherever the horizontal gap
         between consecutive words exceeds _OCR_COL_GAP pixels.
      4. Return list[list[str]] — same format as pdfplumber extract_tables.
    """
    if not _TESSERACT_AVAILABLE or _fitz is None:
        return []
    try:
        img = _PIL_Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except Exception as exc:
        logger.debug("OCR: failed to create PIL image: %s", exc)
        return []

    lang_str = _get_ocr_lang()

    try:
        data = _tesseract.image_to_data(
            img,
            lang=lang_str,
            output_type=_TsrOutput.DICT,
            config="--psm 6 --oem 1",
            timeout=_OCR_PAGE_TIMEOUT,
        )
    except RuntimeError as exc:
        # pytesseract raises RuntimeError on timeout
        logger.warning("OCR: tesseract timeout (>%ds) on page, skipping", _OCR_PAGE_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("OCR: tesseract failed: %s", exc)
        return []

    n = len(data["text"])
    words = []
    for i in range(n):
        text = str(data["text"][i]).strip()
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if text and conf >= _OCR_MIN_CONF:
            left  = int(data["left"][i])
            top   = int(data["top"][i])
            width = int(data["width"][i])
            words.append({
                "text":  text,
                "left":  left,
                "top":   top,
                "right": left + width,
            })

    if not words:
        return []

    # ── Group into visual lines by Y proximity ──────────────────────────────
    words.sort(key=lambda w: (w["top"], w["left"]))
    line_groups: List[List[dict]] = []
    cur_line = [words[0]]
    for w in words[1:]:
        if abs(w["top"] - cur_line[0]["top"]) <= 15:
            cur_line.append(w)
        else:
            line_groups.append(sorted(cur_line, key=lambda x: x["left"]))
            cur_line = [w]
    line_groups.append(sorted(cur_line, key=lambda x: x["left"]))

    # ── Split each line into cells on large horizontal gaps ─────────────────
    table: List[List[str]] = []
    for line in line_groups:
        cells: List[str] = []
        cell_buf = line[0]["text"]
        prev_right = line[0]["right"]
        for w in line[1:]:
            gap = w["left"] - prev_right
            if gap >= _OCR_COL_GAP:
                cells.append(cell_buf.strip())
                cell_buf = w["text"]
            else:
                cell_buf += " " + w["text"]
            prev_right = max(prev_right, w["right"])
        cells.append(cell_buf.strip())
        if any(c for c in cells):
            table.append(cells)

    return table


def _build_table_from_tsv(data: dict) -> List[List[str]]:
    """Convert pytesseract image_to_data dict into a pseudo-table (list of rows).

    Groups words into visual lines by Y proximity (±15 px), then splits
    lines into cells on horizontal gaps >= _OCR_COL_GAP pixels.
    """
    n = len(data.get("text", []))
    words = []
    for i in range(n):
        text = str(data["text"][i]).strip()
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if text and conf >= _OCR_MIN_CONF:
            left  = int(data["left"][i])
            top   = int(data["top"][i])
            width = int(data["width"][i])
            words.append({"text": text, "left": left, "top": top, "right": left + width})
    if not words:
        return []
    words.sort(key=lambda w: (w["top"], w["left"]))
    line_groups: List[List[dict]] = []
    cur_line = [words[0]]
    for w in words[1:]:
        if abs(w["top"] - cur_line[0]["top"]) <= 15:
            cur_line.append(w)
        else:
            line_groups.append(sorted(cur_line, key=lambda x: x["left"]))
            cur_line = [w]
    line_groups.append(sorted(cur_line, key=lambda x: x["left"]))
    table: List[List[str]] = []
    for line in line_groups:
        cells: List[str] = []
        cell_buf = line[0]["text"]
        prev_right = line[0]["right"]
        for w in line[1:]:
            gap = w["left"] - prev_right
            if gap >= _OCR_COL_GAP:
                cells.append(cell_buf.strip())
                cell_buf = w["text"]
            else:
                cell_buf += " " + w["text"]
            prev_right = max(prev_right, w["right"])
        cells.append(cell_buf.strip())
        if any(c for c in cells):
            table.append(cells)
    return table


# ── OpenAI Vision token-per-minute rate limiter ───────────────────────────────
# OpenAI hard limit: 200 000 TPM for gpt-4o-mini (org tier 1).
# We track a rolling 60-second window of estimated token usage and block before
# submitting a request that would push us over _RL_TPM_LIMIT.
# Each page costs at most: ~887 input + 2 048 max_output = 2 935 tokens.
_RL_LOCK: threading.Lock = threading.Lock()
_RL_WINDOW: collections.deque = collections.deque()   # (monotonic_ts, tokens)
_RL_TPM_LIMIT: int = 180_000          # 10 % margin below the 200 K hard limit
# detail=high, 100 DPI A4-landscape (1169x827px) → ~6 tiles × 170 + 85 = 1105 vision tokens
# + max 4096 output → ~5200 actual per page; 7000 gives ~25 pages/min headroom
_RL_EST_PER_PAGE: int = 7_000


def _rate_wait(tokens: int = _RL_EST_PER_PAGE) -> None:
    """Block until the rolling-60 s token window has room for `tokens` more."""
    while True:
        now = time.monotonic()
        with _RL_LOCK:
            # Drop entries older than 60 s
            while _RL_WINDOW and now - _RL_WINDOW[0][0] >= 60.0:
                _RL_WINDOW.popleft()
            used = sum(n for _, n in _RL_WINDOW)
            if used + tokens <= _RL_TPM_LIMIT:
                _RL_WINDOW.append((now, tokens))
                return
            # Must wait until oldest entry expires
            sleep_for = 61.0 - (now - _RL_WINDOW[0][0])
        logger.info(
            "Vision rate-limiter: used=%d/%d — sleeping %.0f s",
            used, _RL_TPM_LIMIT, max(1.0, sleep_for),
        )
        time.sleep(max(1.0, sleep_for))


def _vision_call_bytes(jpeg_bytes: bytes, page_num: int, total: int) -> List[Dict]:
    """Send a pre-rendered JPEG page to GPT-4o-mini Vision.

    Returns spec items as List[Dict] with keys:
      pos, name_raw, article_raw, unit_raw, qty
    GPT extracts and structures items directly — no post-processing needed.
    Returns [] on any error so the caller safely skips the page.
    """
    if not _OPENAI_API_KEY:
        return []
    try:
        from openai import OpenAI
    except ImportError:
        return []

    _rate_wait()   # block until token budget allows this request
    b64 = base64.b64encode(jpeg_bytes).decode()
    prompt = (
        "Page {page}/{total} of a Russian/Kazakh construction/IT equipment specification (scanned PDF).\n"
        "Your task: extract EVERY specification line item from ALL tables on this page. "
        "Do NOT stop early — capture every numbered row until the last one visible.\n\n"
        "Return ONLY a JSON object: {{\"items\": [...]}}\n"
        "Each item has these fields:\n"
        "  pos        — position number string (e.g. \"1\", \"2\", \"1.3\"), empty string if absent\n"
        "  name_raw   — complete item name/description in Cyrillic/Latin, exactly as written "
        "(include model, brand, technical specs if printed in the same cell)\n"
        "  article_raw— article / model code / part number if visible in a separate column, else empty string\n"
        "  unit_raw   — unit of measure (шт, м, кг, компл, м², л, пара, etc.), default \"шт\"\n"
        "  qty        — quantity as a plain number string, default \"1\"\n\n"
        "Rules:\n"
        "- Include ALL numbered rows — IT equipment, cables, sensors, cameras, switches, etc.\n"
        "- Skip only: section headers (bold title rows with no qty), page totals, blank rows.\n"
        "- If a name spans two lines in the PDF, join them with a space.\n"
        "- If the article/model code appears inside the name cell (not a separate column), copy it to article_raw AND keep it in name_raw.\n"
        "- If no items found on this page return {{\"items\": []}}.\n\n"
        "Example output:\n"
        "{{\"items\": [\n"
        "  {{\"pos\":\"1\",\"name_raw\":\"Камера IP купольная уличная 4Мп\",\"article_raw\":\"DS-2CD2143G2-I\",\"unit_raw\":\"шт\",\"qty\":\"8\"}},\n"
        "  {{\"pos\":\"2\",\"name_raw\":\"Коммутатор управляемый PoE 24 порта\",\"article_raw\":\"SG-2424P\",\"unit_raw\":\"шт\",\"qty\":\"2\"}}\n"
        "]}}"
    ).format(page=page_num, total=total)

    try:
        client = OpenAI(api_key=_OPENAI_API_KEY, timeout=90.0, max_retries=2)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=4096,   # was 2048 — pages with 40+ items need more output tokens
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        usage = resp.usage
        if usage:
            logger.info(
                "Vision page %d/%d tokens: in=%d out=%d total=%d",
                page_num, total,
                usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            )
        try:
            data = json.loads(raw)
            raw_items = data.get("items", [])
            if not isinstance(raw_items, list):
                raw_items = []
        except Exception:
            logger.warning("Vision page %d/%d: JSON parse failed: %.120r", page_num, total, raw)
            return []

        items: List[Dict] = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name_raw") or "").strip()
            if not name:
                continue
            items.append({
                "pos":          str(it.get("pos") or "").strip(),
                "name_raw":     name,
                "article_raw":  str(it.get("article_raw") or "").strip(),
                "unit_raw":     str(it.get("unit_raw") or "шт").strip() or "шт",
                "qty":          str(it.get("qty") or "1").strip() or "1",
            })
        logger.info("Vision page %d/%d: extracted %d items", page_num, total, len(items))
        return items
    except Exception as exc:
        logger.warning("Vision OCR page %d/%d failed: %s", page_num, total, exc)
        return []


# Thin wrapper kept for backward compatibility
def _ocr_page_with_vision(pix, page_num: int, total: int) -> List[Dict]:
    return _vision_call_bytes(pix.tobytes("jpeg"), page_num, total)


def _parse_pdf_with_ocr(
    pdf_bytes: bytes,
    progress_cb=None,
) -> Tuple[List[Dict], str]:
    """Full OCR path for scanned PDFs.

    Preferred: GPT-4o-mini Vision (parallel, requires OPENAI_API_KEY).
    Fallback:  Tesseract (sequential, requires pytesseract + tesseract-ocr).

    Two-phase approach:
      Phase A — render all pages to JPEG bytes with PyMuPDF (fast, sequential,
                 avoids PyMuPDF thread-safety issues).
      Phase B — extract tables:
                 Vision: ThreadPoolExecutor(max_workers=8) — all 40 pages in ~5-10 s.
                 Tesseract: sequential with per-page timeout.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    use_vision = bool(_OPENAI_API_KEY)

    if not _FITZ_AVAILABLE or _fitz is None:
        logger.warning("OCR path unavailable: PyMuPDF missing")
        return [], ""
    if not use_vision and not _TESSERACT_AVAILABLE:
        logger.warning("OCR path unavailable: no OPENAI_API_KEY and pytesseract missing")
        return [], ""

    dpi = _VISION_DPI if use_vision else _OCR_DPI
    mat = _fitz.Matrix(dpi / 72, dpi / 72)
    doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    method = "Vision/GPT-4o-mini (x8 parallel)" if use_vision else "Tesseract"
    logger.info("OCR: using %s for %d pages", method, total_pages)
    if progress_cb:
        progress_cb(20, "ocr_start",
                    f"Рендеринг {total_pages} стр. для OCR ({method})...")

    # ── Phase A: render all pages to JPEG bytes (fast, sequential) ────────────
    page_jpegs: List[Optional[bytes]] = []
    for i in range(total_pages):
        try:
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            if i == 0:
                logger.info(
                    "OCR: DPI=%d, page-0 pixmap size=%dx%d px",
                    dpi, pix.width, pix.height,
                )
            page_jpegs.append(pix.tobytes("jpeg"))
        except Exception as exc:
            logger.warning("OCR: page %d render failed: %s", i + 1, exc)
            page_jpegs.append(None)
    doc.close()

    if progress_cb:
        progress_cb(24, "ocr_start",
                    f"Распознавание {total_pages} стр. [{method}]...")

    # ── Phase B: extract tables ───────────────────────────────────────────────
    tables_by_idx: dict = {}

    if use_vision:
        # Parallel Vision calls: submit all pages at once, collect as done
        def _submit(args):
            idx, jpeg = args
            if jpeg is None:
                return idx, []
            return idx, _vision_call_bytes(jpeg, idx + 1, total_pages)

        completed = 0
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="vision") as ex:
            futures = {
                ex.submit(_submit, (i, jpg)): i
                for i, jpg in enumerate(page_jpegs)
            }
            for fut in as_completed(futures):
                completed += 1
                pct = 24 + int(48 * completed / max(total_pages, 1))
                try:
                    idx, table = fut.result()
                    tables_by_idx[idx] = table
                    logger.info("Vision OCR: page %d/%d done", idx + 1, total_pages)
                except Exception as exc:
                    orig_idx = futures[fut]
                    logger.warning("Vision OCR: page %d error: %s", orig_idx + 1, exc)
                    tables_by_idx[orig_idx] = []
                if progress_cb:
                    progress_cb(
                        pct, "ocr_page",
                        f"Vision OCR: {completed}/{total_pages} стр. готово...",
                    )
    else:
        # Sequential Tesseract with per-page timeout
        for i, jpeg in enumerate(page_jpegs):
            pct = 24 + int(48 * i / max(total_pages, 1))
            logger.info("Tesseract OCR: page %d/%d", i + 1, total_pages)
            if progress_cb:
                progress_cb(pct, "ocr_page",
                            f"Tesseract: страница {i + 1}/{total_pages}...")
            if jpeg is None:
                tables_by_idx[i] = []
                continue
            try:
                img = _PIL_Image.open(io.BytesIO(jpeg))
                data = _tesseract.image_to_data(
                    img,
                    lang=_get_ocr_lang(),
                    output_type=_TsrOutput.DICT,
                    config="--psm 6 --oem 1",
                    timeout=_OCR_PAGE_TIMEOUT,
                )
                tables_by_idx[i] = _build_table_from_tsv(data)
            except Exception as exc:
                logger.warning("Tesseract page %d failed: %s", i + 1, exc)
                tables_by_idx[i] = []

    # ── Assemble results in page order ────────────────────────────────────────
    # Vision now returns structured spec items directly — no table parsing needed.
    all_items: List[Dict] = []
    best_proj_name: str = ""

    # Extract project name from the first page using Vision AI
    # (title block / stamp is typically on page 0 for scanned PDFs)
    if use_vision and page_jpegs and page_jpegs[0]:
        best_proj_name = _extract_project_name_ai_vision(page_jpegs[0])
        # If page 0 gave nothing, try page 1
        if not best_proj_name and len(page_jpegs) > 1 and page_jpegs[1]:
            best_proj_name = _extract_project_name_ai_vision(page_jpegs[1])
        logger.info("OCR: project name via Vision AI: %r", best_proj_name[:80] if best_proj_name else "(not found)")

    logger.info("Vision OCR: assembling results from %d pages", total_pages)
    for page_idx in range(total_pages):
        page_items = tables_by_idx.get(page_idx, [])
        if not page_items:
            continue
        all_items.extend(page_items)

    # Renumber sequentially (override per-page pos numbers)
    for idx, item in enumerate(all_items, start=1):
        item["pos"] = str(idx)

    logger.info(
        "OCR extracted %d positions via %s, project=%r",
        len(all_items), method, best_proj_name[:60] if best_proj_name else "",
    )
    return all_items, best_proj_name


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
    # Discard word-fragment overflow: Cyrillic-only text that is long or
    # contains parentheses is almost certainly a name-column fragment that
    # spilled into the article column (e.g. "ТРОЙСТВО)", "ОЙСТВО)").
    # Short compact codes like "СПЛП", "СК", "ПП-П" are valid Russian article
    # abbreviations and must be preserved — they contain no digits or Latin
    # but are genuine product codes in Russian spec documents.
    if not re.search(r"[0-9A-Z]", text):
        if " " in text or len(text) >= 8 or re.search(r"[(){}[\]]", text):
            return ""
    return text


def extract_qty(raw) -> float:
    """Parse quantity from a raw cell string. Supports decimals (0,29 → 0.29)."""
    if raw is None:
        return 1.0
    s = str(raw).strip().replace("\xa0", " ")
    if not s:
        return 1.0
    # Match number with optional decimal part: "0,29" / "3500" / "1.5"
    m = re.search(r"\d[\d\s]*[,.]?\d*", s)
    if not m:
        return 1.0
    num = re.sub(r"\s+", "", m.group(0)).replace(",", ".")
    try:
        v = float(num)
        return v if v > 0 else 1.0
    except ValueError:
        return 1.0


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
_STANDARD_PREFIXES = ("гост", "ст рк", "снип", "сп ", "ту ", "ту-")

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


_STAMP_CODE_RE = re.compile(
    r"^(изм|лист|подпись|дата|инв|взам|формат|кол\.уч|гип|проверил|выполнил|утвердил|н\.конт|н\.к\.|рп |стадия|согласов|разработ)",
    re.IGNORECASE,
)


def _get_code(row: List, code_idx: Optional[int]) -> str:
    if code_idx is None:
        return ""
    primary = _cell(row, code_idx)
    if not primary:
        return ""
    # Reject values that are clearly title-block / stamp-area text bleeding
    # into the code column (e.g. "Изм.", "Лист", "Подпись и дата").
    if _STAMP_CODE_RE.match(primary.strip()):
        return ""
    # Убираем пробелы между цифрами итеративно ("2 4 8" → "248")
    cleaned = primary
    for _ in range(8):
        new = re.sub(r"(\d)\s+(\d)", r"\1\2", cleaned)
        if new == cleaned:
            break
        cleaned = new
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
        if not isinstance(row, (list, tuple)):
            continue
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
    last_section: str = ""   # section header text carried forward for context

    for row in table[data_start:]:
        if not isinstance(row, (list, tuple)):
            continue
        if "pos" in cols:
            pos_raw = _cell(row, cols["pos"])
            pos_val = _is_pos_value(pos_raw)
            if pos_val is None:
                # Check if this is a kit sub-item: pos="-" or pos="" with both
                # name and article present.  Such rows appear in multi-section
                # specs where components have dashes instead of numbers.
                _row_name = _cell(row, cols.get("name"))
                _row_art  = _cell(row, cols.get("article"))
                _row_code = _get_code(row, cols.get("code"))
                _is_dash  = pos_raw.strip() == "-"
                # Normalize article before the _has_content check so that
                # cell fragments that spill over from adjacent columns (e.g.
                # "кт," — the end of "контакт," — which has no Latin/digit
                # characters) are treated as empty and do NOT trigger
                # _has_content, keeping the row as a plain continuation.
                _row_art_norm = normalize_article(_row_art)
                _has_content = bool(_row_name) and bool(_row_art_norm or _row_code)

                # A numbered kit sub-item looks like "1 / Component" or "2) Part" —
                # the name starts with a digit followed by "/" or ")".
                # Such rows are genuine standalone items even if the previous item
                # has no article yet.  Description-continuation rows that happen to
                # carry the article (e.g. the third line of a multi-row Sonar SPM
                # entry) do NOT have a numbered prefix and should be merged instead.
                _is_numbered_subitem = bool(
                    re.match(r"^\d+\s*[/\)]\s", _row_name)
                ) if _row_name else False

                # Section header rows like "1. Пожарная сигнализация" or
                # "2. Оповещение о пожаре" have no article and no code.
                # They must be kept as standalone items, not silently dropped.
                _is_section_header = bool(
                    re.match(r"^\d+\.\s+\S", _row_name)
                ) if (_row_name and not _row_art_norm and not _row_code) else False

                if _is_dash or _is_numbered_subitem or _is_section_header:
                    # Explicit dash rows and numbered kit sub-items → standalone item
                    auto_num += 1
                    pos = f"-{auto_num}"
                    # fall through to normal item processing
                elif _has_content:
                    # Row has name + real article but no position number and is NOT
                    # a numbered sub-item.  Usually treat as a description-continuation
                    # row that carries the article/unit/qty of the parent item.
                    # EXCEPTION: if the previous item is already fully populated
                    # (has its own code) AND the current row brings its own code,
                    # then this is a separate item that lost its position number —
                    # create it as an auto-numbered standalone item instead.
                    if items and items[-1]["kaznisa_code_raw"] and _row_code:
                        # Previous item already complete; treat as new standalone item
                        auto_num += 1
                        pos = f"-{auto_num}"
                        # fall through to normal item processing below
                    elif items:
                        prev = items[-1]
                        cont_qty  = _cell(row, cols.get("qty"))
                        cont_unit = _cell(row, cols.get("unit"))
                        cont_code = _get_code(row, cols.get("code"))
                        # Propagate article if previous item has none
                        if _row_art_norm and not prev["article_raw"]:
                            prev["article_raw"] = _row_art_norm
                        # Propagate unit/qty (last row wins — it usually has the
                        # correct unit like "ком-т" vs the default "шт.")
                        if cont_qty:
                            prev["qty"] = extract_qty(cont_qty)
                        if cont_unit:
                            prev["unit"] = cont_unit
                        if cont_code and not prev["kaznisa_code_raw"]:
                            prev["kaznisa_code_raw"] = cont_code
                        continue
                    else:
                        continue
                else:
                    # Continuation row with no article: merge qty/unit/code only
                    _row_name_raw = _cell(row, cols.get("name"))
                    # If this looks like a section header (has a meaningful name but
                    # no article/code/qty), capture it as context for following items
                    _cont_qty_raw  = _cell(row, cols.get("qty"))
                    _cont_code_raw = _get_code(row, cols.get("code"))
                    _cont_art_raw  = _cell(row, cols.get("article"))
                    if (
                        _row_name_raw
                        and len(_row_name_raw) > 8
                        and not _cont_art_raw
                        and not _cont_code_raw
                        and not _cont_qty_raw
                    ):
                        # Looks like a section/category header — save for context
                        last_section = _row_name_raw.strip()
                    if items:
                        prev = items[-1]
                        cont_qty  = _cont_qty_raw
                        cont_unit = _cell(row, cols.get("unit"))
                        cont_code = _cont_code_raw
                        # If previous item had no qty (=1 default) and this row has qty — use it
                        if cont_qty and prev["qty"] == 1:
                            prev["qty"] = extract_qty(cont_qty)
                        # Fill unit if missing (only if row has BOTH unit and qty — true continuation)
                        if cont_unit and cont_qty and prev["unit"] == "шт.":
                            prev["unit"] = cont_unit
                        # Fill code if missing
                        if cont_code and not prev["kaznisa_code_raw"]:
                            prev["kaznisa_code_raw"] = cont_code
                    continue
            else:
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

        # If name is very short (e.g. "20 мм", "25 мм") and we have a captured
        # section header, prepend it for better semantic search quality.
        # E.g. "20 мм" -> "Трубы гофрированные из ПВХ-пластиката 20 мм"
        if last_section and len(name.strip()) <= 20 and (article or code):
            # Strip ГОСТ/ТУ suffix from section header before prepending
            _sec = re.sub(r'\s+(ТУ|ГОСТ|СТ\s+РК)\s+\S+.*$', '', last_section, flags=re.I).strip()
            if _sec:
                name = (_sec + " " + name).strip()

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
    # qty threshold is 99 999 (not 9 999) so that cable lengths measured in
    # metres (e.g. 15 000 m) are NOT incorrectly treated as garbage data.
    if continuation_cols is not None and cols is continuation_cols and items:
        high_qty = sum(1 for it in items if it["qty"] > 99_999)
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
        if isinstance(row, (list, tuple))
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
        if not isinstance(row, (list, tuple)):
            continue
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
            if isinstance(row, (list, tuple))
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
    sample = " ".join(str(c or "").lower() for row in table[:4] if isinstance(row, (list, tuple)) for c in row)
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
        "ведомость основного",          # Ведомость основного комплекта (document index)
        "ведомость рабочих",            # Ведомость рабочих чертежей (drawing list)
        "ведомость строительных",       # Ведомость строительных работ (construction list)
        "основного комплекта",          # same table, alternate phrasing
    ]
    return any(m in sample for m in non_spec_markers)


def _extract_tables_fast(page) -> list:
    """Extract tables from a pdfplumber page.

    CAD-generated Russian engineering PDFs often have slight line misalignments
    that defeat pdfplumber's default snap_tolerance=3.  We compare two purely
    line-based strategies and return whichever captures more rows:

      1. Default settings  — baseline, works for most clean PDFs
      2. Permissive lines  — higher snap/join tolerances for CAD drawings
         (snap=10 captures rows where border lines are slightly offset)

    Text-based strategies are intentionally excluded: they produce hundreds of
    pseudo-rows from non-table text and confuse column detection.
    """
    # Strategy 1: pdfplumber defaults
    try:
        default_tables = page.extract_tables() or []
    except Exception:
        default_tables = []

    # Strategy 2: looser line snapping for CAD-generated spec sheets
    try:
        permissive_tables = page.extract_tables(table_settings={
            "vertical_strategy":      "lines",
            "horizontal_strategy":    "lines",
            "snap_tolerance":         10,
            "join_tolerance":         5,
            "intersection_tolerance": 5,
        }) or []
    except Exception:
        permissive_tables = []

    default_rows   = sum(len(t) for t in default_tables)
    permissive_rows = sum(len(t) for t in permissive_tables)

    return permissive_tables if permissive_rows > default_rows else default_tables



def _score_project_name(text: str) -> float:
    """Score how likely a text string is a project name (0.0–1.0).

    Used to extract the best project title from a spec PDF.
    Higher score = more likely to be the project/object name.
    """
    if not text:
        return 0.0
    text_l = text.lower()
    score: float = 0.0

    # Keywords common in Russian/Kazakh construction project names
    _PROJECT_KW = (
        "проектирование", "строительство", "реконструкция", "здание",
        "здания", "объект", "объекта", "сооружение", "сооружения",
        "комплекс", "система", "автоматизация", "оснащение",
        "монтаж", "установка", "реализация", "разработка",
    )
    for kw in _PROJECT_KW:
        if kw in text_l:
            score += 0.2
            break  # one match is enough for a strong signal

    # Longer strings are more likely to be project names (up to +0.3)
    score += min(len(text) / 200.0, 0.3)

    # Penalise article-like patterns (e.g. "FS-1024E", "ABC-123")
    if re.search(r"[A-Z]{2,}-\d{2,}", text):
        score -= 0.4

    # Penalise if most chars are digits/Latin (not a project description)
    non_cyrillic = len(re.findall(r"[^а-яёА-ЯЁ\s]", text))
    if non_cyrillic > len(text) * 0.6:
        score -= 0.3

    return max(0.0, min(score, 1.0))


def _extract_project_name_scored(text_pages: List[str]) -> str:
    """Non-AI fallback: pick the highest-scoring line from the first pages.

    Uses _score_project_name heuristics (keyword + length + cyrillic ratio).
    Returns the best candidate line, or "" if nothing scores above threshold.
    """
    THRESHOLD = 0.25
    best_score = 0.0
    best_line  = ""

    for page_text in text_pages:
        if not page_text:
            continue
        # Split into non-empty lines, try both raw lines and sentence fragments
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line in lines:
            if len(line) < 10 or len(line) > 300:
                continue
            score = _score_project_name(line)
            if score > best_score:
                best_score = score
                best_line  = line

    if best_score >= THRESHOLD and best_line:
        return best_line
    return ""


def _extract_project_name_ai(text_pages: List[str]) -> str:
    """Use GPT-4o-mini to extract the project/object name from PDF text.

    text_pages: text content from the first few PDF pages (non-spec cover pages work best).
    Returns the project name string, or empty string if not found / API unavailable.
    """
    if not _OPENAI_API_KEY:
        return ""

    combined = "\n\n---\n\n".join(p[:2000] for p in text_pages[:5] if (p or "").strip())
    if len(combined) < 30:
        return ""

    prompt = (
        "Это текст из PDF-документа строительного или IT-проекта (спецификация оборудования).\n"
        "Найди и напиши ТОЛЬКО официальное наименование объекта/проекта — это название здания, "
        "сооружения, системы, комплекса или строительного проекта, которое обычно указывается "
        "в титульном блоке или штампе документа.\n"
        "Примеры правильного ответа:\n"
        "  «Многофункциональный жилой комплекс по ул. Абая, 10, г. Алматы»\n"
        "  «Система видеонаблюдения административного здания Министерства»\n"
        "  «Реконструкция инженерных систем бизнес-центра Алатау»\n"
        "Правила:\n"
        "  - Пиши только само наименование, без кавычек, без вводных слов, без пояснений.\n"
        "  - Не включай номер документа, шифр, код, дату или ФИО.\n"
        "  - Если наименование не найдено — ответь строго пустой строкой.\n\n"
        f"Текст документа:\n{combined}"
    )

    try:
        from openai import OpenAI as _OAI
        _cli = _OAI(api_key=_OPENAI_API_KEY, timeout=30.0)
        resp = _cli.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        result = (resp.choices[0].message.content or "").strip().strip('"\'«»')
        logger.info("_extract_project_name_ai → %r", result[:80] if result else "(empty)")
        if 10 <= len(result) <= 500:
            return result
        return ""
    except Exception as exc:
        logger.warning("_extract_project_name_ai failed: %s", exc)
        return ""


def _extract_project_name_ai_vision(jpeg_bytes: bytes) -> str:
    """Use GPT-4o-mini Vision to extract the project name from a scanned PDF page.

    Sends the first page image (likely a title block) to Vision.
    Returns project name string or empty string.
    """
    if not _OPENAI_API_KEY or not jpeg_bytes:
        return ""

    import base64 as _b64
    b64 = _b64.b64encode(jpeg_bytes).decode()
    prompt = (
        "Это скан первой страницы строительного/IT-проекта.\n"
        "Найди и напиши ТОЛЬКО официальное наименование объекта или проекта — "
        "обычно это крупный текст в заголовке или в штампе внизу листа.\n"
        "Правила: только само наименование, без кавычек, без номеров документа, "
        "без шифра, без дат и ФИО.\n"
        "Если не найдено — пустая строка."
    )

    try:
        from openai import OpenAI as _OAI
        _cli = _OAI(api_key=_OPENAI_API_KEY, timeout=30.0)
        resp = _cli.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "high",
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0,
            max_tokens=200,
        )
        result = (resp.choices[0].message.content or "").strip().strip('"\'«»')
        logger.info("_extract_project_name_ai_vision → %r", result[:80] if result else "(empty)")
        if 10 <= len(result) <= 500:
            return result
        return ""
    except Exception as exc:
        logger.warning("_extract_project_name_ai_vision failed: %s", exc)
        return ""


def _is_spec_page_text(page_text: str) -> bool:
    """Return True if the page text indicates this page contains the equipment
    specification (Спецификация Оборудования / .СО sheet type).

    Three signals are checked — any one is sufficient:
      1. Explicit header "спецификация оборудования" present on the page.
      2. Document number contains ".со" (Cyrillic) OR ".co" (Latin) suffix
         (sheet type marker) AND the page has all three mandatory spec-table
         column keywords ("поз.", "наименование", "кол-во" / "количество").
      3. Page has all three mandatory spec-table column keywords AND also has
         the equipment-spec article column marker "тип, марка" or "тип,марка".
         This catches continuation sheets (Лист 2, Лист 3…) that repeat the
         full column header row but do not repeat the title "Спецификация
         оборудования" — common in multi-page spec tables.

    If neither signal fires the function returns False and the page is
    skipped when spec pages were found elsewhere in the document.
    """
    if not page_text:
        return False
    tl = page_text.lower()

    # "поз." / "поз " — traditional abbreviation; "позиция" — full word (used
    # in some project templates, e.g. "6_8.1" series from ТехСтройПроект).
    has_poz  = "поз." in tl or "поз " in tl or "позиция" in tl
    has_naim = "наименование" in tl
    has_kol  = ("кол-во" in tl or "количество" in tl
               or "кол." in tl or "коли-" in tl or "кол-" in tl)

    # Signal 1 — explicit spec section header present on this page.
    # Guard: any "Ведомость …" page (Ведомость основного комплекта,
    # Ведомость рабочих чертежей, etc.) lists the spec as ONE data row but
    # is NOT the spec itself.  Such pages have "ведомость" in their text AND
    # lack the position column header that every actual spec sheet carries.
    if "спецификация оборудования" in tl:
        is_vedomost = "ведомость" in tl
        if is_vedomost and not has_poz:
            return False   # document-index page, not the actual spec
        return True

    # Signal 2 — .СО document-type suffix in the title block stamp, plus all
    # three mandatory spec-table column keywords.
    # Note: some PDFs use Latin "CO" instead of Cyrillic "СО" in the stamp,
    # so we check both — ".со" (Cyrillic) and ".co" (Latin only when followed
    # by a word boundary to avoid matching ".com", ".country", etc.).
    _has_so_suffix = ".со" in tl or bool(re.search(r"\.co(?!\w)", tl))
    if _has_so_suffix:
        if has_poz and has_naim and has_kol:
            return True

    # Signal 3 — continuation sheet with full column header row.
    # Multi-page spec tables repeat the column header on every sheet but do not
    # repeat "Спецификация оборудования".  The article column "Тип, марка,
    # обозначение" is very spec-specific — using it as an extra guard prevents
    # false matches on cable-journal or drawing-list pages.
    has_type_col = "тип, марка" in tl or "тип,марка" in tl or "тип марка" in tl
    if has_poz and has_naim and has_kol and has_type_col:
        return True

    return False


def parse_pdf_specification(
    pdf_bytes: bytes,
    progress_cb=None,
) -> Tuple[List[Dict], str]:
    """Parse entire PDF.

    Phase 1 (cheap text scan): identify pages that carry the equipment
    specification.  These pages have "спецификация оборудования" in their
    text OR a document-number ".СО" suffix together with spec table headers.

    Phase 2 (table extraction): process only the detected spec pages.
    Falls back to processing all pages when no spec pages are detected,
    preserving backward compatibility with PDFs that don't use .СО stamps.

    Phase 3 (OCR fallback): if the PDF is fully scanned (no extractable text)
    and no items were found, run pytesseract OCR on rendered page images and
    repeat the extraction logic on the reconstructed pseudo-tables.

    progress_cb(pct: int, stage: str, msg: str) is called at key milestones
    so callers can stream progress to the client.

    Items are NOT deduplicated by position number because multi-section
    documents restart numbering for each section.  Items are returned in
    document order and renumbered sequentially before returning.

    Returns (items, project_name).
    """
    if progress_cb:
        progress_cb(8, "detect", "Анализ структуры PDF...")

    all_items: List[Dict] = []
    last_spec_cols: Optional[Dict] = None
    best_proj_name: str = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)

        # ── Phase 1: detect spec pages via lightweight text scan ─────────────
        page_texts: List[str] = []     # cache text for Phase 1b
        spec_indices: List[int] = []   # 0-based page indices

        # Fast path: use PyMuPDF (fitz) for Phase 1 text extraction — it is
        # ~100x faster than pdfplumber on complex CAD/drawing PDFs.
        if _FITZ_AVAILABLE:
            try:
                _fdoc = _fitz.open(stream=pdf_bytes, filetype="pdf")
                for idx in range(total_pages):
                    try:
                        txt = _fdoc[idx].get_text() or ""
                    except Exception:
                        txt = ""
                    page_texts.append(txt)
                    if _is_spec_page_text(txt):
                        spec_indices.append(idx)
                _fdoc.close()
            except Exception:
                _FITZ_AVAILABLE_local = False
                page_texts.clear()
                spec_indices.clear()
            else:
                _FITZ_AVAILABLE_local = True
        else:
            _FITZ_AVAILABLE_local = False

        if not _FITZ_AVAILABLE_local:
            # Fallback: pdfplumber text extraction with per-page timeout
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
            _text_executor = ThreadPoolExecutor(max_workers=1)
            for idx in range(total_pages):
                try:
                    _future = _text_executor.submit(pdf.pages[idx].extract_text)
                    try:
                        txt = _future.result(timeout=5) or ""
                    except _FuturesTimeout:
                        txt = ""
                    page_texts.append(txt)
                    if _is_spec_page_text(txt):
                        spec_indices.append(idx)
                except Exception:
                    page_texts.append("")
            _text_executor.shutdown(wait=False)

        # ── Fallback: process all pages when no spec markers found ──────────
        if spec_indices:
            logger.info("parse_pdf: found %d spec page(s): %s",
                        len(spec_indices), spec_indices)
        else:
            logger.info(
                "parse_pdf: no spec-page markers found - processing all %d page(s)",
                total_pages,
            )
            spec_indices = list(range(total_pages))

        if progress_cb:
            progress_cb(18, "detect",
                        f"Найдено страниц: {len(spec_indices)} из {total_pages}")

        # ── Extract project name ──────────────────────────────────────────────
        # Prefer pages that are NOT spec pages (cover/title pages have the project name).
        # Fall back to first N pages if the entire doc is spec pages.
        non_spec = [i for i in range(min(total_pages, 10)) if i not in spec_indices]
        candidate_pages = non_spec[:5] if non_spec else list(range(min(5, total_pages)))
        cand_texts = [page_texts[i] for i in candidate_pages]

        # Attempt 1: AI extraction (GPT-4o-mini)
        ai_proj_name = _extract_project_name_ai(cand_texts)
        if ai_proj_name:
            best_proj_name = ai_proj_name
            logger.info("parse_pdf: project name via AI: %r", best_proj_name[:80])

        # Attempt 2: score-based fallback (no API needed)
        if not best_proj_name:
            best_proj_name = _extract_project_name_scored(cand_texts)
            if best_proj_name:
                logger.info("parse_pdf: project name via scoring: %r", best_proj_name[:80])

        # ── Phase 2: extract tables from spec pages ──────────────────────────
        for i, page_idx in enumerate(spec_indices):
            pct = 20 + int(50 * i / max(len(spec_indices), 1))
            page_num = page_idx + 1
            logger.info("parse_pdf: Phase2 page %d/%d (idx=%d)",
                        i + 1, len(spec_indices), page_idx)
            if progress_cb:
                progress_cb(pct, "extract",
                            f"Извлечение таблиц: страница {page_num}...")
            logger.info("parse_pdf: progress_cb done page %d", page_num)

            page = pdf.pages[page_idx]
            logger.info("parse_pdf: page obj acquired page %d", page_num)

            raw_text = (
                page_texts[page_idx]
                if page_idx < len(page_texts)
                else (page.extract_text() or "")
            )
            logger.info("parse_pdf: raw_text len=%d page %d", len(raw_text or ""), page_num)

            logger.info("parse_pdf: extract_tables start page %d", page_num)
            # pdfplumber can hang indefinitely on complex PDFs due to pdfminer
            # lattice-detection bugs. Run in a daemon thread with hard timeout.
            import concurrent.futures as _cf_tab
            _tab_ex = _cf_tab.ThreadPoolExecutor(max_workers=1,
                                                  thread_name_prefix="tab_ex")
            try:
                _tab_fut = _tab_ex.submit(page.extract_tables)
                tables = _tab_fut.result(timeout=30) or []
            except _cf_tab.TimeoutError:
                logger.warning(
                    "parse_pdf: extract_tables TIMEOUT page %d (30s) — skipping",
                    page_num,
                )
                tables = []
            except Exception as _tab_exc:
                logger.warning(
                    "parse_pdf: extract_tables ERROR page %d: %s", page_num, _tab_exc
                )
                tables = []
            finally:
                _tab_ex.shutdown(wait=False)
            logger.info("parse_pdf: extract_tables done page %d — %d table(s)",
                        page_num, len(tables))
            for table in tables:
                if not table:
                    continue
                items, detected_cols = extract_specification_from_page(
                    table,
                    continuation_cols=last_spec_cols,
                )
                if detected_cols is not None:
                    last_spec_cols = detected_cols
                all_items.extend(items)
            logger.info("parse_pdf: page %d done — %d total items so far",
                        page_num, len(all_items))

    if progress_cb:
        progress_cb(72, "parse", "Разбор и нумерация позиций...")

    logger.info("Extracted %d positions, project=%r",
                len(all_items), best_proj_name[:60] if best_proj_name else "")

    # ── Phase 3: OCR fallback for scanned PDFs ───────────────────────────────
    if not all_items and (_TESSERACT_AVAILABLE or _OPENAI_API_KEY) and _FITZ_AVAILABLE:
        if progress_cb:
            progress_cb(20, "ocr_check",
                        "Проверка: сканированный ли PDF...")
        # _is_scanned_pdf can deadlock if a previous fitz operation is stuck.
        # Run it in a fresh daemon thread with a hard timeout.
        import concurrent.futures as _cf
        _scan_ex = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            _scan_fut = _scan_ex.submit(_is_scanned_pdf, pdf_bytes)
            _is_scanned = _scan_fut.result(timeout=15)
        except _cf.TimeoutError:
            logger.warning("_is_scanned_pdf timed out — assuming scanned PDF")
            _is_scanned = True
        except Exception as _e:
            logger.warning("_is_scanned_pdf error: %s — assuming scanned PDF", _e)
            _is_scanned = True
        finally:
            _scan_ex.shutdown(wait=False)
        if _is_scanned:
            all_items, best_proj_name = _parse_pdf_with_ocr(
                pdf_bytes, progress_cb=progress_cb
            )

    # Renumber sequentially + normalise qty to float
    # (Vision OCR path returns qty as a raw string like "0,29" or "3500")
    for idx, item in enumerate(all_items, start=1):
        item["pos"] = str(idx)
        raw_qty = item.get("qty", 1)
        if not isinstance(raw_qty, (int, float)):
            item["qty"] = extract_qty(raw_qty)
        # Normalise unit_raw → unit (Vision uses unit_raw, pdfplumber uses unit)
        if "unit_raw" in item and "unit" not in item:
            item["unit"] = item.pop("unit_raw")

    return all_items, best_proj_name
