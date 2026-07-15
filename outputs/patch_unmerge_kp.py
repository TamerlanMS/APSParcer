# -*- coding: utf-8 -*-
"""
Fix: openpyxl raises MergeCell error when clearing rows 13-500 in КП sheet
because the template has merged cells in that range (e.g. A13:N13).

Solution: unmerge all merged ranges that overlap rows 13-500 BEFORE clearing values.
"""
import ast, sys

FPATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/client/services/excel_generator.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

OLD = (
    '    # Clear old template formulas from the data range before writing.\n'
    '    # Rows 13-500 in the template contain IFERROR(\'WV 4.0\'!...) formulas\n'
    '    # that remain in cells we don\'t overwrite and cause stale references.\n'
    '    for _r in range(13, 501):\n'
    '        for _c in range(1, 15):\n'
    '            kp_ws.cell(row=_r, column=_c).value = None\n'
)

NEW = (
    '    # Clear old template formulas from the data range before writing.\n'
    '    # First unmerge any merged cells in rows 13-500 — openpyxl raises\n'
    '    # MergeCell error when writing to non-top-left cells of a merge.\n'
    '    for _mr in list(kp_ws.merged_cells.ranges):\n'
    '        if _mr.max_row >= 13 and _mr.min_row <= 500:\n'
    '            kp_ws.unmerge_cells(str(_mr))\n'
    '    # Now safely clear values in rows 13-500.\n'
    '    for _r in range(13, 501):\n'
    '        for _c in range(1, 15):\n'
    '            try:\n'
    '                kp_ws.cell(row=_r, column=_c).value = None\n'
    '            except Exception:\n'
    '                pass\n'
)

if OLD not in src:
    print("ERROR: anchor not found")
    idx = src.find("for _r in range(13, 501)")
    if idx != -1:
        print("Context:", repr(src[max(0, idx-200):idx+200]))
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)

ast.parse(src)
print(f"Patch applied. File size: {len(src)} bytes")
print("Syntax OK")
