"""
AIMapper — отправляет структурный слепок прайса в Claude API,
получает JSON-маппинг колонок.

Формат маппинга (возвращаемый Claude):
{
  "supplier_code": "ekf",          // snake_case латиница, уникальный код
  "supplier_name": "EKF",          // читаемое название
  "sheet": "Продукция EKF",        // имя листа с данными
  "header_row": 12,                // строка с заголовками (1-based)
  "data_start_row": 13,            // первая строка данных (1-based)
  "columns": {
    "article":      1,             // номер столбца (1-based) или null
    "name":         2,
    "unit":         6,
    "multiplicity": null,
    "price_base":   7,             // базовая/закупочная цена
    "price_rrts":   9,             // РРЦ
    "price_opt":    8,             // оптовая/дилерская
    "price_partner":10,            // партнёрская/со скидкой
    "ntin":         null,
    "status":       null,
    "comment":      null
  },
  "brand": "EKF",                  // фиксированный бренд (или null если в колонке)
  "brand_column": null,            // колонка с брендом (если не фиксированный)
  "nds_included": true,            // цены включают НДС?
  "nds_rate": 0.12,                // ставка НДС (0.12 = 12%)
  "skip_row_if_empty_col": 1,      // пропускать строку если эта колонка пустая
  "category_col": null             // колонка с категорией (если есть)
}
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Ты эксперт по анализу структуры Excel прайс-листов поставщиков электрооборудования.
Тебе дают структурный слепок .xlsx файла: список листов и первые 15 строк каждого листа.
Твоя задача — определить структуру прайса и вернуть JSON-маппинг.

Правила:
1. Найди лист с основными товарными позициями (обычно называется "Тариф", "Прайс", "Продукция X" и т.п.)
2. Найди строку с заголовками столбцов
3. Сопоставь столбцы с полями схемы
4. Определи, включают ли цены НДС и какая ставка (обычно 12% в Казахстане)
5. Если цены в нескольких колонках — выбери: price_base (базовая/закупочная), price_rrts (РРЦ), price_opt (оптовая/дилерская), price_partner (партнёрская/со скидкой)
6. supplier_code — придумай уникальный латинский snake_case код по названию поставщика

Верни ТОЛЬКО валидный JSON без markdown-обёртки, без объяснений.
Схема ответа строго фиксированная — все ключи обязательны (null если не применимо).
"""

_USER_TEMPLATE = """\
Проанализируй структуру прайс-листа поставщика и верни JSON-маппинг.

Структура файла:
{snapshot_json}

Верни JSON строго в этом формате:
{{
  "supplier_code": "...",
  "supplier_name": "...",
  "sheet": "...",
  "header_row": <число>,
  "data_start_row": <число>,
  "columns": {{
    "article": <число или null>,
    "name": <число или null>,
    "unit": <число или null>,
    "multiplicity": <число или null>,
    "price_base": <число или null>,
    "price_rrts": <число или null>,
    "price_opt": <число или null>,
    "price_partner": <число или null>,
    "ntin": <число или null>,
    "status": <число или null>,
    "comment": <число или null>
  }},
  "brand": "<строка или null>",
  "brand_column": <число или null>,
  "nds_included": <true/false>,
  "nds_rate": <0.12 или другое>,
  "skip_row_if_empty_col": <число или null>,
  "category_col": <число или null>
}}
"""


def analyze_pricelist(snapshot: dict) -> dict:
    """
    Отправляет снепшот в Claude API, возвращает распарсенный маппинг.
    Выбрасывает исключение если API недоступен или ответ невалиден.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY не настроен. Добавьте его в .env")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    user_msg = _USER_TEMPLATE.format(snapshot_json=snapshot_json)

    logger.info("Отправка снепшота в Claude API (%d символов)", len(user_msg))

    message = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = message.content[0].text.strip()
    logger.info("Claude ответил:\n%s", raw[:500])

    # Извлекаем JSON из ответа (на случай если модель всё же добавила текст)
    mapping = _extract_json(raw)
    _validate_mapping(mapping)
    return mapping


def _extract_json(text: str) -> dict:
    """Извлекает первый JSON-объект из текста."""
    # Убираем ```json ... ``` если есть
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()

    # Ищем первый { ... }
    start = text.find("{")
    if start == -1:
        raise ValueError(f"JSON не найден в ответе Claude: {text[:200]}")

    # Находим парный закрывающий }
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("Незакрытый JSON в ответе Claude")


def _validate_mapping(m: dict) -> None:
    """Проверяет обязательные поля маппинга."""
    required = ["supplier_code", "supplier_name", "sheet",
                 "header_row", "data_start_row", "columns"]
    for field in required:
        if field not in m:
            raise ValueError(f"Маппинг не содержит обязательное поле: {field}")
    cols = m["columns"]
    if not isinstance(cols, dict):
        raise ValueError("columns должен быть объектом")
    if not cols.get("article"):
        raise ValueError("columns.article не определён — не могу идентифицировать товары")
