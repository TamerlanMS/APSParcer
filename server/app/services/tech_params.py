"""
tech_params.py — AI-based technical parameter extraction.

Extracts structured key-value technical specs from Russian-language
equipment/cable descriptions typical in construction/IT specifications.

Usage:
    await extract_tech_params(pdf_items)   # modifies in-place

Each item gets:  item["tech_params"] = {"ключ": "значение", ...}
Items without useful descriptions get:  item["tech_params"] = {}

Processed in batches of BATCH_SIZE items per GPT call.
Requires settings.OPENAI_API_KEY.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE      = 15    # items per GPT call — меньше батч → быстрее ответ, меньше truncation
MAX_TOKENS      = 2000  # на 15 позиций ~60 токенов/позиция = 900 + запас
CALL_TIMEOUT    = 20.0  # максимум секунд на один GPT-вызов

# Singleton OpenAI client — не создаём новый на каждый батч
_oai_client = None


def _get_client():
    global _oai_client
    if _oai_client is None:
        from openai import AsyncOpenAI
        _oai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=CALL_TIMEOUT)
    return _oai_client

# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM = (
    "Ты — эксперт по технической документации в сфере IT, "
    "телекоммуникаций, структурированных кабельных систем и строительного оборудования. "
    "Твоя задача — извлекать ключевые технические параметры из наименований позиций."
)

_USER_TEMPLATE = """\
Для каждой позиции извлеки технические параметры из наименования.

ПОЗИЦИИ:
{items_block}

ОТВЕТ — строго JSON-объект с полем "results" — массив, ПО ОДНОМУ объекту на позицию:
{{
  "results": [
    {{"idx": 0, "params": {{"тип": "UTP", "категория": "5e", "длина": "305 м"}}}},
    {{"idx": 1, "params": {{"форм-фактор": "19\\"", "высота": "2U", "тип": "патч-панель"}}}},
    ...
  ]
}}

ПРАВИЛА:
- Ключи параметров — русские, короткие (тип, категория, порты, скорость, мощность, высота, длина и т.п.)
- Максимум 7 параметров на позицию
- Числовые значения включай с единицами (24 порта, 1 Гбит/с, 12U, 305 м)
- Если наименование слишком краткое или нет параметров — верни пустой {{}}: params: {{}}
- НЕ дублируй артикул в params

ПРИМЕРЫ:
Позиция: "Кабель UTP кат. 5e 4x2x0.52 LSZH нг(А)-HF в бухте 305 м"
→ {{"тип": "UTP", "категория": "кат. 5e", "структура": "4x2x0.52", "оболочка": "LSZH", "упаковка": "305 м"}}

Позиция: "Коммутатор управляемый L2+ 24 порта 10/100/1000Base-T 4xSFP+ 10G"
→ {{"уровень": "L2+", "RJ45": "24 × 1 Гбит/с", "SFP+": "4 × 10 Гбит/с"}}

Позиция: "Шкаф телекоммуникационный настенный 19\\\" 9U 600x400 дверь стекло"
→ {{"форм-фактор": "19\\"", "высота": "9U", "глубина": "400 мм", "дверь": "стекло", "монтаж": "настенный"}}

Позиция: "Патч-панель 24 порта кат. 5e RJ45 1U"
→ {{"порты": "24 × RJ45", "категория": "5e", "высота": "1U"}}
"""


# ── Public API ─────────────────────────────────────────────────────────────────

async def extract_tech_params(items: List[Dict]) -> None:
    """Extract technical parameters from item descriptions (modifies in-place).

    Adds item["tech_params"] = {key: value, ...} to every item.
    Items with empty/short names get tech_params = {}.
    Silently skips if OPENAI_API_KEY is not configured.
    """
    if not settings.OPENAI_API_KEY:
        logger.debug("tech_params: OPENAI_API_KEY not set, skipping extraction")
        for item in items:
            item.setdefault("tech_params", {})
        return

    # Pre-initialise so all items have the key even if extraction fails
    for item in items:
        item.setdefault("tech_params", {})

    # Build batches
    tasks = []
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        tasks.append(_process_batch(batch, start))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("tech_params batch %d failed: %s", i, r)

    extracted = sum(1 for it in items if it.get("tech_params"))
    logger.info("tech_params: extracted params for %d/%d items", extracted, len(items))


# ── Internal ───────────────────────────────────────────────────────────────────

async def _process_batch(batch: List[Dict], offset: int) -> None:
    """Send one batch to GPT-4o-mini and write results back."""
    try:
        client = _get_client()
    except Exception as exc:
        logger.error("tech_params: OpenAI client error: %s", exc)
        return

    # Compose item lines
    lines: List[str] = []
    for i, item in enumerate(batch):
        name = (item.get("name_raw") or "").strip()[:250]
        art  = (item.get("article_raw") or "").strip()[:60]
        if art:
            lines.append(f"{i}. [{art}] {name}")
        else:
            lines.append(f"{i}. {name}")

    items_block = "\n".join(lines)
    prompt = _USER_TEMPLATE.format(items_block=items_block)

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("tech_params batch (offset=%d) GPT error: %s", offset, exc)
        return

    # Unwrap — model returns {"results": [...]} or bare [...]
    result_list = None
    if isinstance(parsed, list):
        result_list = parsed
    elif isinstance(parsed, dict):
        for key in ("results", "items", "positions", "data"):
            if key in parsed and isinstance(parsed[key], list):
                result_list = parsed[key]
                break

    if not result_list:
        logger.warning("tech_params batch (offset=%d): unexpected shape: %s",
                       offset, str(parsed)[:200])
        return

    for entry in result_list:
        idx    = entry.get("idx")
        params = entry.get("params", {})
        if not isinstance(idx, int) or not (0 <= idx < len(batch)):
            continue
        if not isinstance(params, dict):
            continue
        # Clean up: keep only string keys and string/number values
        clean = {
            str(k).strip(): str(v).strip()
            for k, v in params.items()
            if k and v and str(v).strip()
        }
        if clean:
            batch[idx]["tech_params"] = clean


def tech_params_to_text(tech_params: dict) -> str:
    """Convert tech_params dict to a compact text string for vector queries."""
    if not tech_params:
        return ""
    return " ".join(f"{k} {v}" for k, v in tech_params.items())
