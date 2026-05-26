"""
Excel cache service — builds and stores base_template.xlsm on the server.

The base template is WV_template.xlsm with БД and Const sheets pre-filled
from the current database. It is rebuilt in the background after every
products/constants import so clients can download it instead of fetching
thousands of rows themselves.
"""
import asyncio
import io
import logging
import math
import os
import shutil
from typing import List, Dict

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Product, BrandConstant, CurrencyRate, Manager

logger = logging.getLogger(__name__)

TEMPLATE_PATH = "/app/assets/WV_template.xlsm"
CACHE_PATH    = "/app/data/base_template.xlsm"

# ── Column indices (1-based) — must match client/services/excel_generator.py ──

BD_NUM     = 1; BD_ARTICLE = 2; BD_NAME   = 3; BD_UNIT    = 4
BD_KAZNISA = 5; BD_RRTS    = 6; BD_MRC    = 7; BD_OPT     = 8
BD_PARTNER = 9; BD_BRAND   = 10; BD_MULT  = 11; BD_KAZ_CODE = 12

CONST_MANAGER   = 2;  CONST_POSITION = 3;  CONST_EMAIL   = 4;  CONST_PHONE   = 5
CONST_BRAND     = 8;  CONST_MARGIN   = 9;  CONST_LOGISTICS = 10; CONST_RATE  = 11
CONST_CURRATE   = 12; CONST_NDS      = 13; CONST_GP      = 14
CONST_CUR_NAME  = 22; CONST_CUR_RATE = 23


def _fill_bd(ws, products: List) -> None:
    last_row = ws.max_row
    for r in range(3, last_row + 1):
        for col in range(1, 13):
            cell = ws.cell(row=r, column=col)
            if cell.value is not None and not (
                    isinstance(cell.value, str) and cell.value.startswith("=")):
                cell.value = None
    for i, p in enumerate(products):
        row = 3 + i
        ws.cell(row=row, column=BD_NUM,      value=p.num        or (i + 1))
        ws.cell(row=row, column=BD_ARTICLE,  value=p.article    or "")
        ws.cell(row=row, column=BD_NAME,     value=p.name       or "")
        ws.cell(row=row, column=BD_UNIT,     value=p.unit       or "")
        ws.cell(row=row, column=BD_KAZNISA,  value=p.kaznisa    or None)
        ws.cell(row=row, column=BD_RRTS,     value=p.rrts       or None)
        ws.cell(row=row, column=BD_MRC,      value=p.mrc        or None)
        ws.cell(row=row, column=BD_OPT,      value=p.opt        or None)
        ws.cell(row=row, column=BD_PARTNER,  value=p.partner    or None)
        ws.cell(row=row, column=BD_BRAND,    value=p.brand      or "")
        ws.cell(row=row, column=BD_MULT,     value=p.multiplicity or None)
        ws.cell(row=row, column=BD_KAZ_CODE, value=p.kaznisa_code or "")


def _fill_const(ws, brands: List, managers: List, currencies: List) -> None:
    last_row = max(ws.max_row,
                   2 + max(len(brands), len(managers), len(currencies), 1))
    clear_cols = (list(range(CONST_MANAGER, CONST_GP + 1))
                  + [CONST_CUR_NAME, CONST_CUR_RATE])
    for r in range(2, last_row + 1):
        for col in clear_cols:
            cell = ws.cell(row=r, column=col)
            if cell.value is not None and not (
                    isinstance(cell.value, str) and cell.value.startswith("=")):
                cell.value = None

    for i, m in enumerate(managers):
        row = 2 + i
        ws.cell(row=row, column=CONST_MANAGER,   value=m.full_name or "")
        ws.cell(row=row, column=CONST_POSITION,  value=m.position  or "")
        ws.cell(row=row, column=CONST_EMAIL,     value=m.email     or "")
        ws.cell(row=row, column=CONST_PHONE,     value=m.phone     or "")

    for i, b in enumerate(brands):
        row = 2 + i
        ws.cell(row=row, column=CONST_BRAND,     value=b.brand       or "")
        ws.cell(row=row, column=CONST_MARGIN,    value=b.margin)
        ws.cell(row=row, column=CONST_LOGISTICS, value=b.logistics)
        ws.cell(row=row, column=CONST_RATE,      value=b.rate)
        ws.cell(row=row, column=CONST_CURRATE,   value=b.currency_rate)
        ws.cell(row=row, column=CONST_NDS,       value=b.nds)
        ws.cell(row=row, column=CONST_GP,        value=b.gp)

    for i, c in enumerate(currencies):
        row = 2 + i
        ws.cell(row=row, column=CONST_CUR_NAME, value=c.name or "")
        ws.cell(row=row, column=CONST_CUR_RATE, value=c.rate)


def _build_sync(products: List, brands: List,
                managers: List, currencies: List) -> None:
    """CPU-bound: copy template, fill sheets, save. Runs in thread executor."""
    if not os.path.exists(TEMPLATE_PATH):
        logger.warning("excel_cache: template not found at %s", TEMPLATE_PATH)
        return
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    shutil.copyfile(TEMPLATE_PATH, tmp)
    wb = openpyxl.load_workbook(tmp, keep_vba=True, data_only=False)

    if "БД" in wb.sheetnames:
        _fill_bd(wb["БД"], products)
    else:
        logger.warning("excel_cache: sheet 'БД' not found in template")

    if "Const" in wb.sheetnames:
        _fill_const(wb["Const"], brands, managers, currencies)
    else:
        logger.warning("excel_cache: sheet 'Const' not found in template")

    wb.save(tmp)
    os.replace(tmp, CACHE_PATH)   # atomic replace
    logger.info("excel_cache: rebuilt %s (%d products, %d brands)",
                CACHE_PATH, len(products), len(brands))


async def rebuild_base_template(db: AsyncSession) -> None:
    """Fetch data from DB and rebuild cached base_template.xlsm in background."""
    try:
        products_res  = await db.execute(
            select(Product).where(Product.is_active == True).order_by(Product.num))
        brands_res    = await db.execute(select(BrandConstant))
        managers_res  = await db.execute(
            select(Manager).where(Manager.is_active == True).order_by(Manager.full_name))
        currencies_res = await db.execute(select(CurrencyRate))

        products   = products_res.scalars().all()
        brands     = brands_res.scalars().all()
        managers   = managers_res.scalars().all()
        currencies = currencies_res.scalars().all()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _build_sync,
            list(products), list(brands), list(managers), list(currencies)
        )
    except Exception as exc:
        logger.error("excel_cache: rebuild failed: %s", exc)
