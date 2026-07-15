# -*- coding: utf-8 -*-
"""
Fix: позиции без артикула/кода но с наименованием и количеством
пропускались парсером (светильники, кабели, трубы на страницах без
буквенного обозначения позиции).

Пример: "Светодиодный светильник PROLED PL-8 | ШТ | 291"
        "Кабель ВВГнг(А)-LS-0.66 3х1.5мм2 | м | 10960"

_has_content проверял только (артикул ИЛИ код). Теперь добавляем (кол-во > 0).
_is_new_standalone: если нет артикула/кода но есть кол-во → самостоятельная позиция.
"""
import ast, sys

FPATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/services/pdf_parser.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

# ── Fix A: вычисляем qty заранее + добавляем в _has_content ──────────────────
OLD_A = (
    '                _row_art_norm = normalize_article(_row_art)\n'
    '                _has_content = bool(_row_name) and bool(_row_art_norm or _row_code)\n'
)
NEW_A = (
    '                _row_art_norm = normalize_article(_row_art)\n'
    '                # Pre-compute qty for the has-content check and standalone detection.\n'
    '                # Items with name + qty but no article/code are valid spec entries\n'
    '                # (e.g. cable, pipe, luminaire rows on pages without position codes).\n'
    '                _row_qty_prelim = _cell(row, cols.get("qty")) if cols.get("qty") is not None else ""\n'
    '                _row_qty_val    = extract_qty(_row_qty_prelim) if _row_qty_prelim else 0\n'
    '                _has_content = bool(_row_name) and bool(_row_art_norm or _row_code or _row_qty_val > 0)\n'
)

if OLD_A not in src:
    print("ERROR: anchor A not found")
    idx = src.find("_has_content = bool(_row_name)")
    print("Context:", repr(src[max(0,idx-100):idx+120]))
    sys.exit(1)

src = src.replace(OLD_A, NEW_A, 1)
print("Fix A: _has_content now also fires when name + qty present")

# ── Fix B: _is_new_standalone → имя+кол-во без артикула = самостоятельная поз. ─
OLD_B = (
    '                        _is_new_standalone = (\n'
    '                            prev.get("is_heading")\n'
    '                            or (_prev_art_b and cont_qty and extract_qty(cont_qty) > 0)\n'
    '                        )\n'
)
NEW_B = (
    '                        _is_new_standalone = (\n'
    '                            prev.get("is_heading")\n'
    '                            or (_prev_art_b and cont_qty and extract_qty(cont_qty) > 0)\n'
    '                            # Positional-code-less items with their own qty:\n'
    '                            # e.g. "Светильник PROLED PL-8 | ШТ | 291"\n'
    '                            or (not _row_art_norm and not _row_code and _row_qty_val > 0)\n'
    '                        )\n'
)

if OLD_B not in src:
    print("ERROR: anchor B not found")
    idx = src.find("_is_new_standalone")
    print("Context:", repr(src[max(0,idx-50):idx+200]))
    sys.exit(1)

src = src.replace(OLD_B, NEW_B, 1)
print("Fix B: _is_new_standalone includes rows with name+qty but no article/code")

# ── Validate + write ──────────────────────────────────────────────────────────
ast.parse(src)
with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)
print(f"pdf_parser.py: {len(src)} bytes — Syntax OK")
print("Done. Restart server to apply.")
