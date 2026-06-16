"""
Парсер прайса DKC.
Лист: "Прайс ДКС"
Строка 11 — заголовок, данные с строки 17.
Строки 12-16 и промежуточные строки = категории (col 6 пустой = категория/секция).
Столбцы:
  F=Код(6), H=Описание(8), I=Ед(9), J=Кол-во в упаковке(10),
  K=Цена с НДС(11), L=Цена без НДС(12)
НДС=12%.
"""
from __future__ import annotations
from typing import List, Optional
import openpyxl

from app.services.price_parser.base import BaseParser, NormalizedItem, _clean_str

SHEET    = "Прайс ДКС"
HDR_ROW  = 11
DATA_ROW = 17

C_ARTICLE        = 6
C_NAME           = 8
C_UNIT           = 9
C_MULT           = 10
C_PRICE_WITH_NDS = 11
C_PRICE_NO_NDS   = 12


class DKCParser(BaseParser):
    supplier_code = "dkc"
    supplier_name = "DKC"

    def parse(self, file_path: str) -> List[NormalizedItem]:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb[SHEET]
        items: List[NormalizedItem] = []
        current_category: Optional[str] = None

        for row in ws.iter_rows(min_row=DATA_ROW, values_only=True):
            article_val = row[C_ARTICLE - 1]
            article = _clean_str(article_val)

            # Строка-категория: col A-E или 1-5 содержит текст, col 6 пуст
            if not article:
                # Пробуем выцепить категорию из первых колонок
                for i in range(5):
                    v = _clean_str(row[i])
                    if v:
                        current_category = v
                        break
                continue

            name = _clean_str(row[C_NAME - 1])
            if not name:
                continue

            price_no_nds   = self._to_float(row[C_PRICE_NO_NDS   - 1])
            price_with_nds = self._to_float(row[C_PRICE_WITH_NDS - 1])

            items.append(NormalizedItem(
                article      = article,
                name         = name,
                unit         = _clean_str(row[C_UNIT - 1]) or "шт",
                multiplicity = self._to_int(row[C_MULT - 1]),
                brand        = "DKC",
                price_base   = price_no_nds,
                price_rrts   = price_with_nds,
                category     = current_category,
            ))

        wb.close()
        return items
