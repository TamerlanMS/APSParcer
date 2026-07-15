# -*- coding: utf-8 -*-
"""
Fix: vector-only PDFs (AutoCAD text-as-paths) get 0 items because:
1. _OCR_DPI=150 is too low for CAD fonts (text height ~10-15px → unreadable)
2. All 21 vector pages are OCR'd including floor plans (wasteful, slow)

Changes:
A) Add _detect_table_pages_by_lines(): uses pdfplumber line strategy to
   find pages that actually contain rectangular spec tables (>=4 cols, >=5 rows).
   Floor plan pages have complex shapes, not regular tables → they're skipped.

B) In Phase 3b (vector-only OCR), pass ocr_dpi=250 and a page whitelist
   of detected table pages to _parse_pdf_with_ocr().

C) Add ocr_dpi and page_whitelist params to _parse_pdf_with_ocr() so
   only targeted pages are rendered and OCR'd at the right DPI.
"""
import ast, sys, re

FPATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/services/pdf_parser.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

# ─────────────────────────────────────────────────────────────────────────────
# A) Add _detect_table_pages_by_lines() after _has_vector_only_pages()
# ─────────────────────────────────────────────────────────────────────────────
OLD_A = (
    'def _parse_cid_pdf_via_pdfplumber(pdf_bytes: bytes) -> List[Dict]:\n'
    '    """Extract pos/code/qty from CID-encoded spec PDFs via pdfplumber.\n'
)
NEW_A = (
    'def _detect_table_pages_by_lines(pdf_bytes: bytes) -> List[int]:\n'
    '    """Return 0-based page indices that contain a rectangular spec table.\n'
    '\n'
    '    Uses pdfplumber line-strategy table detection — works on vector PDFs\n'
    '    where text is drawn as paths but table borders are still proper lines.\n'
    '    Floor-plan pages have complex shapes rather than regular grid tables\n'
    '    and are therefore NOT returned by this function.\n'
    '    \"\"\"\n'
    '    try:\n'
    '        import pdfplumber as _plb\n'
    '        import io as _io2\n'
    '        _settings = {\n'
    '            "vertical_strategy":   "lines",\n'
    '            "horizontal_strategy": "lines",\n'
    '            "snap_tolerance":  6,\n'
    '            "join_tolerance":  6,\n'
    '            "min_words_vertical":   0,\n'
    '            "min_words_horizontal": 0,\n'
    '        }\n'
    '        table_pages: List[int] = []\n'
    '        with _plb.open(_io2.BytesIO(pdf_bytes)) as _pdf:\n'
    '            for _pi, _pg in enumerate(_pdf.pages):\n'
    '                try:\n'
    '                    tbls = _pg.find_tables(_settings)\n'
    '                    for _t in tbls:\n'
    '                        rows = len(_t.rows)\n'
    '                        cols = len(_t.rows[0].cells) if _t.rows else 0\n'
    '                        if rows >= 5 and cols >= 4:\n'
    '                            table_pages.append(_pi)\n'
    '                            break\n'
    '                except Exception:\n'
    '                    pass\n'
    '        logger.info(\n'
    '            "_detect_table_pages_by_lines: found spec-table pages: %s",\n'
    '            table_pages,\n'
    '        )\n'
    '        return table_pages\n'
    '    except Exception as _exc:\n'
    '        logger.warning("_detect_table_pages_by_lines failed: %s", _exc)\n'
    '        return []\n'
    '\n'
    '\n'
    'def _parse_cid_pdf_via_pdfplumber(pdf_bytes: bytes) -> List[Dict]:\n'
    '    """Extract pos/code/qty from CID-encoded spec PDFs via pdfplumber.\n'
)

if OLD_A not in src:
    print("ERROR: anchor A not found")
    idx = src.find("def _parse_cid_pdf_via_pdfplumber")
    print("Context:", repr(src[max(0,idx-50):idx+100]))
    sys.exit(1)

src = src.replace(OLD_A, NEW_A, 1)
print("Fix A applied: added _detect_table_pages_by_lines()")

# ─────────────────────────────────────────────────────────────────────────────
# B) Add ocr_dpi + page_whitelist params to _parse_pdf_with_ocr()
# ─────────────────────────────────────────────────────────────────────────────
OLD_B = (
    'def _parse_pdf_with_ocr(\n'
    '    pdf_bytes: bytes,\n'
    '    progress_cb=None,\n'
    '    skip_readable_nonspec: bool = False,\n'
    '    tail_first: bool = False,\n'
    ') -> Tuple[List[Dict], str]:\n'
)
NEW_B = (
    'def _parse_pdf_with_ocr(\n'
    '    pdf_bytes: bytes,\n'
    '    progress_cb=None,\n'
    '    skip_readable_nonspec: bool = False,\n'
    '    tail_first: bool = False,\n'
    '    ocr_dpi: Optional[int] = None,\n'
    '    page_whitelist: Optional[List[int]] = None,\n'
    ') -> Tuple[List[Dict], str]:\n'
)

if OLD_B not in src:
    print("ERROR: anchor B not found")
    sys.exit(1)

src = src.replace(OLD_B, NEW_B, 1)
print("Fix B applied: added ocr_dpi + page_whitelist params")

# ─────────────────────────────────────────────────────────────────────────────
# C) Use ocr_dpi param inside _parse_pdf_with_ocr instead of global _OCR_DPI
# ─────────────────────────────────────────────────────────────────────────────
OLD_C = '    dpi = _VISION_DPI if use_vision else _OCR_DPI\n'
NEW_C = '    dpi = _VISION_DPI if use_vision else (ocr_dpi or _OCR_DPI)\n'

if OLD_C not in src:
    print("ERROR: anchor C not found")
    idx = src.find("_VISION_DPI if use_vision else")
    print("Context:", repr(src[max(0,idx-50):idx+100]))
    sys.exit(1)

src = src.replace(OLD_C, NEW_C, 1)
print("Fix C applied: use ocr_dpi param in DPI selection")

# ─────────────────────────────────────────────────────────────────────────────
# D) Apply page_whitelist when rendering pages in Phase A of _parse_pdf_with_ocr
# ─────────────────────────────────────────────────────────────────────────────
OLD_D = (
    '    page_jpegs: List[Optional[bytes]] = []\n'
    '    for i in range(total_pages):\n'
    '        try:\n'
    '            if i in _readable_nonspec:\n'
    '                page_jpegs.append(None)  # skip — readable non-spec\n'
    '                continue\n'
)
NEW_D = (
    '    page_jpegs: List[Optional[bytes]] = []\n'
    '    for i in range(total_pages):\n'
    '        try:\n'
    '            if i in _readable_nonspec:\n'
    '                page_jpegs.append(None)  # skip — readable non-spec\n'
    '                continue\n'
    '            if page_whitelist is not None and i not in page_whitelist:\n'
    '                page_jpegs.append(None)  # skip — not in whitelist\n'
    '                continue\n'
)

if OLD_D not in src:
    print("ERROR: anchor D not found")
    sys.exit(1)

src = src.replace(OLD_D, NEW_D, 1)
print("Fix D applied: page_whitelist filtering in render loop")

# ─────────────────────────────────────────────────────────────────────────────
# E) In Phase 3b, detect table pages and pass them + 250 DPI
# ─────────────────────────────────────────────────────────────────────────────
OLD_E = (
    '    if not all_items and (_TESSERACT_AVAILABLE or _OPENAI_API_KEY) and _FITZ_AVAILABLE:\n'
    '        if _has_vector_only_pages(pdf_bytes):\n'
    '            logger.info(\n'
    '                "parse_pdf: vector-only PDF (AutoCAD text-to-outlines) — routing to OCR"\n'
    '            )\n'
    '            if progress_cb:\n'
    '                progress_cb(20, "ocr", "Векторный PDF AutoCAD: запуск OCR...")\n'
    '            all_items, best_proj_name = _parse_pdf_with_ocr(\n'
    '                pdf_bytes,\n'
    '                progress_cb=progress_cb,\n'
    '                skip_readable_nonspec=True,\n'
    '                tail_first=True,\n'
    '            )\n'
)
NEW_E = (
    '    if not all_items and (_TESSERACT_AVAILABLE or _OPENAI_API_KEY) and _FITZ_AVAILABLE:\n'
    '        if _has_vector_only_pages(pdf_bytes):\n'
    '            logger.info(\n'
    '                "parse_pdf: vector-only PDF (AutoCAD text-to-outlines) — routing to OCR"\n'
    '            )\n'
    '            if progress_cb:\n'
    '                progress_cb(20, "ocr", "Векторный PDF AutoCAD: запуск OCR...")\n'
    '            # Detect which pages actually contain spec tables (vs floor plans)\n'
    '            # using pdfplumber line detection. This avoids OCRing large drawing\n'
    '            # pages and focuses on the rectangular spec table sheets.\n'
    '            _tbl_pages = _detect_table_pages_by_lines(pdf_bytes)\n'
    '            _whitelist = _tbl_pages if _tbl_pages else None\n'
    '            if _whitelist:\n'
    '                logger.info(\n'
    '                    "parse_pdf: vector OCR restricted to table pages: %s",\n'
    '                    _whitelist,\n'
    '                )\n'
    '            all_items, best_proj_name = _parse_pdf_with_ocr(\n'
    '                pdf_bytes,\n'
    '                progress_cb=progress_cb,\n'
    '                skip_readable_nonspec=True,\n'
    '                tail_first=True,\n'
    '                ocr_dpi=250,\n'
    '                page_whitelist=_whitelist,\n'
    '            )\n'
)

if OLD_E not in src:
    print("ERROR: anchor E not found")
    idx = src.find("vector-only PDF (AutoCAD text-to-outlines)")
    print("Context:", repr(src[max(0,idx-100):idx+400]))
    sys.exit(1)

src = src.replace(OLD_E, NEW_E, 1)
print("Fix E applied: table page detection + 250 DPI in Phase 3b")

# ─────────────────────────────────────────────────────────────────────────────
# Write + validate
# ─────────────────────────────────────────────────────────────────────────────
with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)

ast.parse(src)
print(f"File size: {len(src)} bytes")
print("Syntax OK — done.")
