# -*- coding: utf-8 -*-
"""
Fix: строки вида "на вводе: ВН-32-3Р 25А IEK-1шт" и "на выводе: ВА47-29, 16А"
являются подстроками описания щита и не должны становиться отдельными позициями.

Паттерны для пропуска (в начале ячейки "name", регистронезависимо):
  - "на вводе"   / "На вводе"
  - "на выводе"  / "На выводе"
  - "а) Вводной" / "б) На линиях" / "в) Расцепитель" и т.п.
  - "вводной:"   (без буквенного префикса)
  - "на линиях"
"""
import ast, sys, re

FPATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/services/pdf_parser.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

OLD = (
    '    for row in table[data_start:]:\n'
    '        if not isinstance(row, (list, tuple)):\n'
    '            continue\n'
    '        _is_heading_row = False   # reset each iteration; set True for section headers\n'
    '        _panel_code_for_sub = ""  # щиток own code to re-emit as standalone after heading\n'
)
NEW = (
    '    # Pre-compile щит sub-description filter (used inside the loop)\n'
    '    _VVODE_RE = re.compile(\n'
    '        r"^(?:[а-яА-ЯёЁa-zA-Z]\\)\\s*)?(?:на\\s+вводе|на\\s+выводе|вводн|на\\s+линиях|расцепитель)",\n'
    '        re.IGNORECASE,\n'
    '    )\n'
    '\n'
    '    for row in table[data_start:]:\n'
    '        if not isinstance(row, (list, tuple)):\n'
    '            continue\n'
    '        # Skip щит sub-description lines that appear in the "Наименование" column\n'
    '        # as continuation text: "а) На вводе: ВН-32-3Р 25А IEK", "б) На линиях: ВА47-29..."\n'
    '        # These are NOT separate spec items.\n'
    '        if cols.get("name") is not None:\n'
    '            _quick_name = _cell(row, cols["name"]).strip()\n'
    '            if _quick_name and _VVODE_RE.match(_quick_name):\n'
    '                continue\n'
    '        _is_heading_row = False   # reset each iteration; set True for section headers\n'
    '        _panel_code_for_sub = ""  # щиток own code to re-emit as standalone after heading\n'
)

if OLD not in src:
    print("ERROR: anchor not found")
    idx = src.find("for row in table[data_start:]")
    print("Context:", repr(src[max(0,idx-50):idx+200]))
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

ast.parse(src)
with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)
print(f"pdf_parser.py: {len(src)} bytes — Syntax OK")
print("Fix: rows starting with 'на вводе/выводе/линиях' are now skipped")
