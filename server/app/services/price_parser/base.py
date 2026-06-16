"""
Базовый класс парсера прайса поставщика.
Нормализованная схема одной позиции — NormalizedItem.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List
import re


@dataclass
class NormalizedItem:
    """Единая схема позиции после парсинга любого прайса."""
    article:     str
    name:        str
    unit:        str             = "шт"
    multiplicity: Optional[int] = None
    brand:       Optional[str]  = None
    # Цены (без НДС, KZT)
    price_base:    Optional[float] = None   # Базовая / тариф
    price_rrts:    Optional[float] = None   # РРЦ
    price_opt:     Optional[float] = None   # Оптовая / дилерская
    price_partner: Optional[float] = None   # Партнёрская / со скидкой
    # Мета
    ntin:         Optional[str]  = None
    status:       Optional[str]  = None     # "Заказная", "В наличии", …
    category:     Optional[str]  = None
    comment:      Optional[str]  = None

    def __post_init__(self):
        self.article = _clean_str(self.article)
        self.name    = _clean_str(self.name)
        self.unit    = _clean_str(self.unit) or "шт"

    def to_dict(self) -> dict:
        return {
            "article":      self.article,
            "name":         self.name,
            "unit":         self.unit,
            "multiplicity": self.multiplicity,
            "brand":        self.brand,
            "price_base":   self.price_base,
            "price_rrts":   self.price_rrts,
            "price_opt":    self.price_opt,
            "price_partner": self.price_partner,
            "ntin":         self.ntin,
            "status":       self.status,
            "category":     self.category,
            "comment":      self.comment,
        }


class BaseParser:
    supplier_code: str = "unknown"
    supplier_name: str = "Unknown"

    def parse(self, file_path: str) -> List[NormalizedItem]:
        raise NotImplementedError

    @staticmethod
    def _to_float(val) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            v = float(val)
            return round(v, 2) if v != 0 else None
        s = str(val).strip().replace(" ", "").replace(",", ".")
        s = re.sub(r"[^\d.]", "", s)
        try:
            v = float(s)
            return round(v, 2) if v != 0 else None
        except ValueError:
            return None

    @staticmethod
    def _to_int(val) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(float(str(val).strip()))
        except (ValueError, TypeError):
            return None


def _clean_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip().replace("\xa0", " ").replace("\n", " ")
