"""
Парсер прайса IEK GROUP.
Лист: "Прайс"
Строка 7 — заголовок, данные с строки 9 (строка 8 пустая).
Столбцы (1-based):
  1=Артикул, 2=Наименование, 8=Ед., 9=NTIN, 10=Статус,
  13=Кратность, 15=Базовая с НДС, 16=РРЦ с НДС, 17=Оптовая с НДС,
  20=Цена со статусной скидкой с НДС
НДС=12%.
"""
from __future__ import annotations
from typing import List
import openpyxl

from app.services.price_parser.base import BaseParser, NormalizedItem, _clean_str

SHEET    = "Прайс"
HDR_ROW  = 7
DATA_ROW = 9
NDS      = 1.12

C_ARTICLE     = 1
C_NAME        = 2
C_UNIT        = 8
C_NTIN        = 9
C_STATUS      = 10
C_MULT        = 13
C_PRICE_BASE  = 15
C_PRICE_RRTS  = 16
C_PRICE_OPT   = 17
C_PRICE_DISC  = 20  # со статусной скидкой


class IEKParser(BaseParser):
    supplier_code = "iek"
    supplier_name = "IEK GROUP"

    def parse(self, file_path: str) -> List[NormalizedItem]:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb[SHEET]
        items: List[NormalizedItem] = []

        def excl(v):
            f = self._to_float(v)
            return round(f / NDS, 2) if f else None

        for row in ws.iter_rows(min_row=DATA_ROW, values_only=True):
            article = _clean_str(row[C_ARTICLE - 1])
            if not article:
                continue
            name = _clean_str(row[C_NAME - 1])
            if not name:
                continue

            items.append(NormalizedItem(
                article       = article,
                name          = name,
                unit          = _clean_str(row[C_UNIT - 1]) or "шт",
                multiplicity  = self._to_int(row[C_MULT - 1]),
                brand         = "IEK",
                price_base    = excl(row[C_PRICE_BASE - 1]),
                price_rrts    = excl(row[C_PRICE_RRTS - 1]),
                price_opt     = excl(row[C_PRICE_OPT  - 1]),
                price_partner = excl(row[C_PRICE_DISC  - 1]),
                ntin          = _clean_str(row[C_NTIN   - 1]) or None,
                status        = _clean_str(row[C_STATUS - 1]) or None,
                category      = _clean_str(row[4 - 1])  or None,  # col4=Категория
            ))

        wb.close()
        return items
