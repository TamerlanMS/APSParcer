"""
ParserRegistry — единая точка входа для парсинга прайсов.

Поток:
  1. Строим snapshot файла
  2. Ищем кэшированный маппинг в БД по file_signature
  3. Если нет → вызываем Claude API → получаем маппинг → сохраняем в кэш
  4. Парсим файл по маппингу через GenericParser
  5. Возвращаем (supplier_code, supplier_name, items)
"""
from __future__ import annotations
import hashlib
import json
import logging
from typing import Optional

from app.services.price_parser.snapshot       import build_snapshot
from app.services.price_parser.ai_mapper      import analyze_pricelist
from app.services.price_parser.generic_parser import parse_by_mapping
from app.services.price_parser.base           import NormalizedItem

logger = logging.getLogger(__name__)


def _file_signature(file_path: str, snapshot: dict) -> str:
    """MD5 от первых листов+строк — достаточно для определения 'того же формата'."""
    raw = json.dumps(snapshot["sheets"][:2], ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()


class ParserRegistry:
    """
    Реестр парсеров на основе Claude API с кэшем маппингов.
    Для работы с БД (кэш) передавать db в parse_file.
    """

    async def parse_file(
        self,
        file_path: str,
        db=None,          # AsyncSession | None
        force_remap: bool = False,
    ) -> tuple[Optional[str], Optional[str], list[NormalizedItem]]:
        """
        Возвращает (supplier_code, supplier_name, items).
        Если supplier_code = None — поставщик не определён.
        """
        # 1. Строим снепшот
        snapshot  = build_snapshot(file_path)
        signature = _file_signature(file_path, snapshot)

        # 2. Ищем кэш в БД
        mapping: Optional[dict] = None
        cached_id: Optional[int] = None

        if db and not force_remap:
            mapping, cached_id = await _load_cached_mapping(db, signature)
            if mapping:
                logger.info("Маппинг найден в кэше (id=%s)", cached_id)

        # 3. Если кэша нет — вызываем Claude API
        if mapping is None:
            logger.info("Кэш не найден — вызываем Claude API")
            try:
                mapping = analyze_pricelist(snapshot)
                logger.info("Claude определил поставщика: %s", mapping.get("supplier_code"))
            except Exception as exc:
                logger.error("Claude API ошибка: %s", exc)
                return None, None, []

            # Сохраняем в кэш
            if db:
                await _save_mapping(db, signature, mapping)

        # 4. Парсим файл
        try:
            items = parse_by_mapping(file_path, mapping)
            logger.info("Распарсено %d позиций для %s", len(items), mapping.get("supplier_code"))
        except Exception as exc:
            logger.error("Ошибка парсинга по маппингу: %s", exc)
            # Сброс кэша и повторная попытка с Claude
            if db and cached_id and not force_remap:
                await _invalidate_mapping(db, cached_id)
                logger.info("Кэш инвалидирован, повторный вызов Claude API")
                return await self.parse_file(file_path, db=db, force_remap=True)
            return None, None, []

        return (
            mapping.get("supplier_code"),
            mapping.get("supplier_name"),
            items,
        )

    def get_signature(self, file_path: str) -> str:
        snapshot = build_snapshot(file_path)
        return _file_signature(file_path, snapshot)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _load_cached_mapping(db, signature: str):
    """Ищет маппинг по сигнатуре в supplier_mappings."""
    from sqlalchemy import select
    from app.models.models import SupplierMapping
    result = await db.execute(
        select(SupplierMapping)
        .where(SupplierMapping.file_signature == signature)
        .order_by(SupplierMapping.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return json.loads(row.mapping_json), row.id
    return None, None


async def _save_mapping(db, signature: str, mapping: dict):
    """Сохраняет маппинг в supplier_mappings (создаёт Supplier если нет)."""
    from sqlalchemy import select
    from app.models.models import Supplier, SupplierMapping

    code = mapping.get("supplier_code", "unknown")
    name = mapping.get("supplier_name", code)

    # Найти или создать Supplier
    res = await db.execute(select(Supplier).where(Supplier.code == code))
    supplier = res.scalar_one_or_none()
    if not supplier:
        supplier = Supplier(code=code, name=name)
        db.add(supplier)
        await db.flush()

    sm = SupplierMapping(
        supplier_id    = supplier.id,
        file_signature = signature,
        mapping_json   = json.dumps(mapping, ensure_ascii=False),
        source         = "ai",
    )
    db.add(sm)
    await db.commit()
    logger.info("Маппинг сохранён в кэш для '%s'", code)


async def _invalidate_mapping(db, mapping_id: int):
    """Удаляет устаревший маппинг из кэша."""
    from app.models.models import SupplierMapping
    row = await db.get(SupplierMapping, mapping_id)
    if row:
        await db.delete(row)
        await db.commit()
