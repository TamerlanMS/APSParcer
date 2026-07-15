# -*- coding: utf-8 -*-
"""
Patch: когда AI-ползунок включён — использовать Vision OCR как ОСНОВНОЙ
метод извлечения позиций для ЛЮБОГО типа PDF (не только для векторных/скан).

Changes:
1. pdf_parser.py — добавляем ai_mode: bool = False к parse_pdf_specification()
   + AI-приоритетный блок: если ai_mode и есть OpenAI ключ — идём через Vision OCR
   сразу (раньше Phase 1+2 pdfplumber). При 0 результатов — fallback на pdfplumber.

2. pdf.py — передаём ai_mode=use_ai в run_in_executor через functools.partial.
"""
import ast, sys

# ─── PATCH 1: pdf_parser.py ──────────────────────────────────────────────────
PARSER_PATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/services/pdf_parser.py"

with open(PARSER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

# A) Добавляем ai_mode параметр в сигнатуру
OLD_A = (
    'def parse_pdf_specification(\n'
    '    pdf_bytes: bytes,\n'
    '    progress_cb=None,\n'
    ') -> Tuple[List[Dict], str]:\n'
)
NEW_A = (
    'def parse_pdf_specification(\n'
    '    pdf_bytes: bytes,\n'
    '    progress_cb=None,\n'
    '    ai_mode: bool = False,\n'
    ') -> Tuple[List[Dict], str]:\n'
)

if OLD_A not in src:
    print("ERROR: anchor A not found")
    idx = src.find("def parse_pdf_specification")
    print("Context:", repr(src[idx:idx+200]))
    sys.exit(1)

src = src.replace(OLD_A, NEW_A, 1)
print("Fix A: added ai_mode param to parse_pdf_specification()")

# B) Добавляем AI-приоритетный блок после CID-check, перед pdfplumber.open()
OLD_B = (
    '        except Exception as _cid_exc:\n'
    '            logger.warning("CID early check failed: %s — continuing with pdfplumber", _cid_exc)\n'
    '\n'
    '    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:\n'
)
NEW_B = (
    '        except Exception as _cid_exc:\n'
    '            logger.warning("CID early check failed: %s — continuing with pdfplumber", _cid_exc)\n'
    '\n'
    '    # ── AI-priority path ─────────────────────────────────────────────────────\n'
    '    # Когда AI-режим включён: используем Vision OCR как ОСНОВНОЙ метод.\n'
    '    # Работает для ЛЮБОГО типа PDF: текстового, скана, векторного, CID-шрифтов.\n'
    '    # Если Vision вернул 0 позиций — fallback на pdfplumber (Phase 1+2).\n'
    '    if ai_mode and _OPENAI_API_KEY and _FITZ_AVAILABLE and not all_items:\n'
    '        logger.info("parse_pdf: ai_mode=True — Vision OCR as primary extraction")\n'
    '        if progress_cb:\n'
    '            progress_cb(10, "ai_ocr", "AI режим: Vision OCR (приоритет)...")\n'
    '        _ai_items, _ai_proj = _parse_pdf_with_ocr(\n'
    '            pdf_bytes,\n'
    '            progress_cb=progress_cb,\n'
    '            skip_readable_nonspec=True,\n'
    '        )\n'
    '        if _ai_items:\n'
    '            logger.info("parse_pdf: Vision OCR returned %d items — done", len(_ai_items))\n'
    '            _real_pos = 0\n'
    '            for _it in _ai_items:\n'
    '                if _it.get("is_heading"):\n'
    '                    continue\n'
    '                _real_pos += 1\n'
    '                _it["pos"] = str(_real_pos)\n'
    '                _raw_qty = _it.get("qty", 1)\n'
    '                if not isinstance(_raw_qty, (int, float)):\n'
    '                    _it["qty"] = extract_qty(_raw_qty)\n'
    '                if "unit_raw" in _it and "unit" not in _it:\n'
    '                    _it["unit"] = _it.pop("unit_raw")\n'
    '            return _ai_items, _ai_proj\n'
    '        logger.info("parse_pdf: Vision OCR returned 0 items — falling back to pdfplumber")\n'
    '\n'
    '    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:\n'
)

if OLD_B not in src:
    print("ERROR: anchor B not found")
    idx = src.find("CID early check failed")
    print("Context:", repr(src[max(0,idx-50):idx+200]))
    sys.exit(1)

src = src.replace(OLD_B, NEW_B, 1)
print("Fix B: added AI-priority path before pdfplumber Phase 1+2")

# Validate + write
ast.parse(src)
with open(PARSER_PATH, "w", encoding="utf-8") as f:
    f.write(src)
print(f"pdf_parser.py: {len(src)} bytes — Syntax OK")

# ─── PATCH 2: pdf.py ─────────────────────────────────────────────────────────
PDF_API_PATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/api/pdf.py"

with open(PDF_API_PATH, "r", encoding="utf-8") as f:
    src2 = f.read()

# A) Добавляем import functools после существующих импортов
OLD_2A = 'from concurrent.futures import ThreadPoolExecutor\n'
NEW_2A = 'from concurrent.futures import ThreadPoolExecutor\nimport functools\n'

if OLD_2A not in src2:
    print("ERROR: anchor 2A not found")
    sys.exit(1)
if 'import functools' in src2:
    print("Fix 2A: functools already imported — skipping")
else:
    src2 = src2.replace(OLD_2A, NEW_2A, 1)
    print("Fix 2A: added import functools")

# B) Первый parse-stream endpoint (строка ~134-135)
OLD_2B = (
    '            pdf_items, project_name = await loop.run_in_executor(\n'
    '                _PDF_EXECUTOR, parse_pdf_specification, content, _progress\n'
    '            )\n'
    '            logger.info("PDF parse DONE: %d items, project=%r",\n'
)
NEW_2B = (
    '            _parse_fn = functools.partial(parse_pdf_specification, ai_mode=use_ai)\n'
    '            pdf_items, project_name = await loop.run_in_executor(\n'
    '                _PDF_EXECUTOR, _parse_fn, content, _progress\n'
    '            )\n'
    '            logger.info("PDF parse DONE: %d items, project=%r",\n'
)

if OLD_2B not in src2:
    print("ERROR: anchor 2B not found")
    sys.exit(1)

src2 = src2.replace(OLD_2B, NEW_2B, 1)
print("Fix 2B: parse-stream endpoint passes ai_mode to parser")

# C) Multi-stream endpoint (строка ~292-293)
OLD_2C = (
    '            pdf_items, project_name = await loop.run_in_executor(\n'
    '                _PDF_EXECUTOR, parse_pdf_specification, content, _progress\n'
    '            )\n'
    '\n'
    '            if not project_name:\n'
    '                project_name = _os.path.splitext(fname)[0].strip()\n'
    '\n'
    '            if not pdf_items:\n'
)
NEW_2C = (
    '            _parse_fn = functools.partial(parse_pdf_specification, ai_mode=use_ai)\n'
    '            pdf_items, project_name = await loop.run_in_executor(\n'
    '                _PDF_EXECUTOR, _parse_fn, content, _progress\n'
    '            )\n'
    '\n'
    '            if not project_name:\n'
    '                project_name = _os.path.splitext(fname)[0].strip()\n'
    '\n'
    '            if not pdf_items:\n'
)

if OLD_2C not in src2:
    print("ERROR: anchor 2C not found")
    sys.exit(1)

src2 = src2.replace(OLD_2C, NEW_2C, 1)
print("Fix 2C: multi-stream endpoint passes ai_mode to parser")

# D) Non-streaming parse_pdf endpoint (строка ~413-414)
# use_ai определяется ПОСЛЕ вызова парсера в этом эндпоинте,
# поэтому считаем inline: ai_mode and bool(settings.OPENAI_API_KEY)
OLD_2D = (
    '        pdf_items, project_name = await loop.run_in_executor(\n'
    '            _PDF_EXECUTOR, parse_pdf_specification, content, None\n'
    '        )\n'
    '    except ValueError as e:\n'
)
NEW_2D = (
    '        _parse_fn_sync = functools.partial(\n'
    '            parse_pdf_specification,\n'
    '            ai_mode=ai_mode and bool(settings.OPENAI_API_KEY),\n'
    '        )\n'
    '        pdf_items, project_name = await loop.run_in_executor(\n'
    '            _PDF_EXECUTOR, _parse_fn_sync, content, None\n'
    '        )\n'
    '    except ValueError as e:\n'
)

if OLD_2D not in src2:
    print("ERROR: anchor 2D not found")
    sys.exit(1)

src2 = src2.replace(OLD_2D, NEW_2D, 1)
print("Fix 2D: sync parse_pdf endpoint passes ai_mode to parser")

# Validate + write
ast.parse(src2)
with open(PDF_API_PATH, "w", encoding="utf-8") as f:
    f.write(src2)
print(f"pdf.py: {len(src2)} bytes — Syntax OK")
print("\nAll patches applied successfully.")
