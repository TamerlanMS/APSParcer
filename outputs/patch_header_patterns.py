# -*- coding: utf-8 -*-
"""
Fix: HEADER_PATTERNS["article"] не распознаёт "Тип. марка. обозначение"
(с точками) — встречается в некоторых шаблонах проектов.

После _norm_for_pattern: "тип.марка.обозначение" — ни "типмарка" ни "тип,марка"
не входят как подстрока.

Fix: добавляем "тип.марка" в список паттернов.
"""
import ast, sys

FPATH = "/sessions/adoring-gifted-heisenberg/mnt/APSParcer/server/app/services/pdf_parser.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

OLD = (
    '    "article": ["типмарка",\n'
    '                "тип,марка",\n'
    '                "типмарки",\n'
)
NEW = (
    '    "article": ["типмарка",\n'
    '                "тип,марка",\n'
    '                "тип.марка",\n'   # "Тип. марка. обозначение" (с точками)
    '                "типмарки",\n'
)

if OLD not in src:
    print("ERROR: anchor not found")
    idx = src.find('"article"')
    print("Context:", repr(src[idx:idx+200]))
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

ast.parse(src)
with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)
print(f"pdf_parser.py: {len(src)} bytes — Syntax OK")
print('Fix: added "тип.марка" to HEADER_PATTERNS["article"]')
