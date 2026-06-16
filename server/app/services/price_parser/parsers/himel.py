"""
Парсер прайса Himel.
Лист: "Тариф"
Строка 3 — заголовок: Референс | Описание | Ед. изм. | Кратность | Тариф без НДС | Комментарий | NTIN
Данные с строки 4.
"""
from __future__ import annotations
from typing import List
import openpyxl

from app.services.price_parser.base import BaseParser, NormalizedItem, _clean_str

SHEET    = "Тариф"
HDR_ROW  = 3
DATA_ROW = 4

# Индексы столбцов (1-based)
C_ARTICLE  = 1
C_NAME     = 2
C_UNIT     = 3
C_MULT     = 4
C_PRICE    = 5   # Тариф без НДС
C_COMMENT  = 6
C_NTIN     = 7


class HimelParser(BaseParser):
    supplier_code = "himel"
    supplier_name = "Himel"

    def parse(self, file_path: str) -> List[NormalizedItem]:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb[SHEET]
        items: List[NormalizedItem] = []

        for row in ws.iter_rows(min_row=DATA_ROW, values_only=True):
            article = _clean_str(row[C_ARTICLE - 1])
            if not article:
                continue

            price_base = self._to_float(row[C_PRICE - 1])

            items.append(NormalizedItem(
                article      = article,
                name         = _clean_str(row[C_NAME - 1]),
                unit         = _clean_str(row[C_UNIT - 1]) or "шт",
                multiplicity = self._to_int(row[C_MULT - 1]),
                brand        = "Himel",
                price_base   = price_base,
                ntin         = _clean_str(row[C_NTIN - 1]) or None,
                comment      = _clean_str(row[C_COMMENT - 1]) or None,
            ))

        wb.close()
        return items
