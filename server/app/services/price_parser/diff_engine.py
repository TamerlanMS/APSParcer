"""
DiffEngine — сравнение распарсенных позиций с текущей БД.
Возвращает структурированный отчёт об изменениях.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from app.services.price_parser.base import NormalizedItem

# Поля цен, которые мы отслеживаем в Product
PRICE_FIELDS = ["price_base", "price_rrts", "price_opt", "price_partner"]

# Маппинг полей NormalizedItem → поля Product
FIELD_MAP = {
    "price_base":    "opt",        # базовая → opt (закупочная)
    "price_rrts":    "rrts",       # РРЦ → rrts
    "price_opt":     "opt",        # оптовая → opt (приоритет ниже)
    "price_partner": "partner",    # партнёрская → partner
}

# Поля для маппинга имён/единиц
META_FIELDS = ["name", "unit", "multiplicity", "brand"]


@dataclass
class DiffRecord:
    article:    str
    kind:       str     # "new" | "updated" | "deleted"
    name:       str     = ""
    brand:      str     = ""
    changes:    Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # changes = {"rrts": {"old": 100.0, "new": 120.0}, ...}


@dataclass
class DiffReport:
    supplier_code: str
    filename:      str
    rows_total:    int = 0
    rows_new:      int = 0
    rows_updated:  int = 0
    rows_deleted:  int = 0
    rows_skipped:  int = 0
    records:       List[DiffRecord] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "supplier_code": self.supplier_code,
            "filename":      self.filename,
            "rows_total":    self.rows_total,
            "rows_new":      self.rows_new,
            "rows_updated":  self.rows_updated,
            "rows_deleted":  self.rows_deleted,
            "rows_skipped":  self.rows_skipped,
        }

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "records": [
                {
                    "article": r.article,
                    "kind":    r.kind,
                    "name":    r.name,
                    "brand":   r.brand,
                    "changes": r.changes,
                }
                for r in self.records
            ],
        }


def build_diff(
    supplier_code: str,
    filename: str,
    incoming: List[NormalizedItem],
    existing: Dict[str, dict],   # article → product dict из БД
    mark_missing_as_deleted: bool = False,
) -> DiffReport:
    """
    incoming      — результат парсинга прайса
    existing      — текущее состояние Product в БД (по артикулу)
    mark_missing_as_deleted — помечать ли позиции из БД, которых нет в прайсе
    """
    report = DiffReport(supplier_code=supplier_code, filename=filename,
                        rows_total=len(incoming))

    incoming_articles: set = set()

    for item in incoming:
        article = item.article
        incoming_articles.add(article)

        if not article:
            report.rows_skipped += 1
            continue

        if article not in existing:
            # Новая позиция
            report.rows_new += 1
            rec = DiffRecord(
                article = article,
                kind    = "new",
                name    = item.name,
                brand   = item.brand or "",
                changes = _extract_price_changes(item, {}),
            )
            report.records.append(rec)
        else:
            # Существующая — проверяем изменения цен
            existing_prod = existing[article]
            changes = _extract_price_changes(item, existing_prod)
            if changes:
                report.rows_updated += 1
                report.records.append(DiffRecord(
                    article = article,
                    kind    = "updated",
                    name    = item.name or existing_prod.get("name", ""),
                    brand   = item.brand or existing_prod.get("brand", "") or "",
                    changes = changes,
                ))
            else:
                report.rows_skipped += 1

    if mark_missing_as_deleted:
        for article, prod in existing.items():
            if article not in incoming_articles:
                report.rows_deleted += 1
                report.records.append(DiffRecord(
                    article = article,
                    kind    = "deleted",
                    name    = prod.get("name", ""),
                    brand   = prod.get("brand", "") or "",
                ))

    return report


def _extract_price_changes(
    item: NormalizedItem,
    existing: dict,
) -> Dict[str, Dict[str, Any]]:
    """Возвращает словарь полей с изменёнными ценами."""
    changes: Dict[str, Dict[str, Any]] = {}

    price_map = {
        "rrts":    item.price_rrts,
        "opt":     item.price_opt or item.price_base,
        "partner": item.price_partner,
    }

    for db_field, new_val in price_map.items():
        if new_val is None:
            continue
        old_val = existing.get(db_field)
        # Считаем изменением только если разница > 0.01 или поле новое
        if old_val is None or abs(float(old_val) - float(new_val)) > 0.01:
            changes[db_field] = {"old": old_val, "new": new_val}

    return changes
