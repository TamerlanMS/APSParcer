"""
Генерация выходного .xlsm на основе шаблона assets/WV_template.xlsm.

Структура шаблона:
  Лист «WV 4.0»: A=Бренд, B=Артикул, C=Наименование, D=Ед.изм.,
    E=Кол-во, F=Кратность, G=Константа цена, H=Цена себес,
    I=Сумма себес, J=Цена КП, K=Сумма КП, L=Код КазНИИСА,
    M=Комментарии, N=Срок поставки.
    Пишем только «вводные»: A(бренд), B(артикул), E(кол-во), G(конст.), M, N.
    Формулы C, D, F, H-L пересчитаются в Excel автоматически.

  Лист «БД»: заголовок на строке 2, данные с 3-й.
    A=№GQ, B=Артикул, C=Наименование, D=Ед.изм., E=КазНИИСА,
    F=РРЦ, G=МРЦ, H=Опт., I=Партнёр, J=Бренд, K=Кратность, L=Код КазНИИСА.

  Лист «Const»: заголовок на строке 1, данные с 2-й.
    B=Менеджер, C=Должность, D=Email, E=Телефон (менеджеры);
    H=Бренд, I=Маржа, J=Логистика, K=Расценка, L=Курс, M=НДС, N=ГП (бренд-константы);
    V=Валюта, W=Курс к тенге (курсы валют).

  Лист «КП»: шапка (менеджер C3, проект F3, клиент F4).
    Данные записываем прямыми значениями начиная с строки 13,
    только найденные позиции (status != 'not_found').
    A=Бренд, B=Артикул, C=Наименование, D=Ед.изм., E=Кол-во,
    F=Цена КП, G=Сумма КП, H=Комментарии, I=Срок поставки,
    J=Цена КазНИИСА, K=Сумма КазНИИСА, L=Код КазНИИСА,
    M=РРЦ в тнг, N=Сумма РРЦ.
"""
import math
import os
import sys
import shutil
import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, PatternFill, Alignment
from typing import List, Dict, Optional


# ── Колонки WV 4.0 (1-based) ─────────────────────────────────────────────────
WV_BRAND      = 1   # A — записываем напрямую
WV_ARTICLE    = 2   # B — записываем напрямую
WV_NAME       = 3   # C — формула (не трогаем)
WV_UNIT       = 4   # D — формула
WV_QTY        = 5   # E — записываем
WV_MULT       = 6   # F — формула
WV_CONST_PRC  = 7   # G — ручная константа цены
WV_PRICE_SEB  = 8   # H — формула
WV_SUM_SEB    = 9   # I — формула
WV_PRICE_KP   = 10  # J — формула
WV_SUM_KP     = 11  # K — формула
WV_KAZNIISA   = 12  # L — формула
WV_COMMENT    = 13  # M — пользовательский текст
WV_DELIVERY   = 14  # N — пользовательский текст

# ── Колонки БД (1-based) ─────────────────────────────────────────────────────
BD_NUM        = 1   # A — № GQ
BD_ARTICLE    = 2   # B — Артикул
BD_NAME       = 3   # C — Наименование
BD_UNIT       = 4   # D — Ед. изм.
BD_KAZNISA    = 5   # E — КазНИИСА цена
BD_RRTS       = 6   # F — РРЦ
BD_MRC        = 7   # G — МРЦ
BD_OPT        = 8   # H — Опт
BD_PARTNER    = 9   # I — Партнёр
BD_BRAND      = 10  # J — Бренд
BD_MULT       = 11  # K — Кратность
BD_KAZ_CODE   = 12  # L — Код КазНИИСА

# ── Колонки Const (1-based) ──────────────────────────────────────────────────
CONST_MANAGER  = 2   # B — Менеджер
CONST_POSITION = 3   # C — Должность
CONST_EMAIL    = 4   # D — Email
CONST_PHONE    = 5   # E — Телефон
CONST_BRAND    = 8   # H — Бренд
CONST_MARGIN   = 9   # I — Маржа
CONST_LOGISTICS= 10  # J — Логистика
CONST_RATE     = 11  # K — Расценка
CONST_CURRATE  = 12  # L — Курс к тенге
CONST_NDS      = 13  # M — НДС
CONST_GP       = 14  # N — ГП
CONST_CUR_NAME = 22  # V — Название валюты
CONST_CUR_RATE = 23  # W — Курс к тенге (валюты)
CONST_RATE_LIST_COL = 31   # AE — список типов расценки для data validation

RATE_TYPE_LABELS = [
    "Сумма КазНИИСА", "Цена КазНИИСА", "РРЦ", "МРЦ",
    "Опт", "Цена ГП", "Сумма ГП", "Проект",
]


# ── Колонки КП (1-based) ─────────────────────────────────────────────────────
KP_BRAND      = 1   # A
KP_ARTICLE    = 2   # B
KP_NAME       = 3   # C
KP_UNIT       = 4   # D
KP_QTY        = 5   # E
KP_PRICE_KP   = 6   # F — Цена КП
KP_SUM_KP     = 7   # G — Сумма КП
KP_COMMENT    = 8   # H
KP_DELIVERY   = 9   # I
KP_PRICE_KAZ  = 10  # J — Цена КазНИИСА
KP_SUM_KAZ    = 11  # K
KP_KAZ_CODE   = 12  # L
KP_PRICE_RRC  = 13  # M — РРЦ в тнг
KP_SUM_RRC    = 14  # N

KP_DATA_START = 13   # первая строка данных в КП
KP_DATA_MAX   = 500  # последняя строка данных (до "Итого")

RATE_FIELD = {1: "rrts", 2: "mrc", 3: "opt", 4: "partner", 5: "kaznisa"}


# ─────────────────────────────────────────────────────────────────────────────

def _template_path() -> str:
    base_candidates = [
        os.path.dirname(os.path.abspath(sys.argv[0])),
        getattr(sys, "_MEIPASS", None),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    ]
    for base in base_candidates:
        if not base:
            continue
        candidate = os.path.join(base, "assets", "WV_template.xlsm")
        if os.path.isfile(candidate):
            return candidate
    return ""


def _clear_input_rows(ws, start_row: int = 2, end_row: int = 1000):
    """Очищаем только пользовательские колонки WV 4.0."""
    for r in range(start_row, end_row + 1):
        for col in (WV_BRAND, WV_ARTICLE, WV_QTY,
                    WV_CONST_PRC, WV_COMMENT, WV_DELIVERY):
            cell = ws.cell(row=r, column=col)
            if cell.value is not None and not (
                    isinstance(cell.value, str) and cell.value.startswith("=")):
                cell.value = None


# ── x14:dataValidation (расширенный Excel 2010+) ─────────────────────────────
# openpyxl удаляет <x14:dataValidations> при load/save.
# Восстанавливаем его патчем на уровне ZIP после каждого save.

_X14_EXT_BLOCK = (
    '<ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}"'
    ' xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
    '<x14:dataValidations count="1"'
    ' xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">'
    '<x14:dataValidation type="list" allowBlank="1"'
    ' showInputMessage="1" showErrorMessage="1">'
    '<x14:formula1><xm:f>Const!$AE$1:$AE$18</xm:f></x14:formula1>'
    '<xm:sqref>H1:L1</xm:sqref>'
    '</x14:dataValidation>'
    '</x14:dataValidations>'
    '</ext>'
)


def _inject_x14_dv(xlsm_path: str) -> None:
    """Восстанавливает x14:dataValidations в листе WV 4.0 после openpyxl save."""
    import zipfile, io, re as _re

    def _find_sheet_file(zf, name: str) -> str:
        wb  = zf.read("xl/workbook.xml").decode("utf-8", errors="replace")
        rel = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="replace")
        sheets = _re.findall(r'<sheet[^>]+name="([^"]+)"[^>]+r:id="([^"]+)"', wb)
        # rels can have Id/Target in either order; also Target may start with /xl/ or xl/
        rid_to_target = {}
        for m in _re.finditer(r'<Relationship[^>]+>', rel):
            tag = m.group()
            id_m  = _re.search(r'Id="([^"]+)"', tag)
            tgt_m = _re.search(r'Target="([^"]+)"', tag)
            if id_m and tgt_m:
                tgt = tgt_m.group(1).lstrip("/")   # strip leading /
                if not tgt.startswith("xl/"):
                    tgt = "xl/" + tgt
                rid_to_target[id_m.group(1)] = tgt
        for sname, rid in sheets:
            if sname == name:
                return rid_to_target.get(rid, "")
        return ""

    try:
        with open(xlsm_path, "rb") as fh:
            raw = fh.read()

        in_buf, out_buf = io.BytesIO(raw), io.BytesIO()

        with zipfile.ZipFile(in_buf, "r") as zin:
            sheet_file = _find_sheet_file(zin, "WV 4.0")
            if not sheet_file:
                print(f"[x14_dv] WV 4.0 not found in {xlsm_path}")
                return

            with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == sheet_file:
                        xml = data.decode("utf-8", errors="replace")
                        if "x14:dataValidations" not in xml:
                            if "<extLst>" in xml:
                                xml = xml.replace("</extLst>",
                                                  _X14_EXT_BLOCK + "</extLst>", 1)
                            else:
                                xml = xml.replace("</worksheet>",
                                                  "<extLst>" + _X14_EXT_BLOCK
                                                  + "</extLst></worksheet>", 1)
                        data = xml.encode("utf-8")
                    zout.writestr(item, data)

        with open(xlsm_path, "wb") as fh:
            fh.write(out_buf.getvalue())

        print(f"[x14_dv] injected into {xlsm_path}")
    except Exception as exc:
        print(f"[x14_dv] failed {xlsm_path}: {exc}")



_HEADING_FILL = PatternFill("solid", fgColor="D9E1F2")  # light blue-gray
_HEADING_FONT = Font(bold=True)

def _apply_heading_style(ws, row: int, max_col: int = 14) -> None:
    """Apply bold + fill to all cells in a heading row."""
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        try:
            cell.font = _HEADING_FONT
            cell.fill = _HEADING_FILL
        except (TypeError, AttributeError):
            pass

def _fill_bd_sheet(wb: openpyxl.Workbook, products: List[Dict]):
    """Заполняет лист БД актуальными данными из сервера."""
    if "БД" not in wb.sheetnames:
        return
    ws = wb["БД"]

    # Очищаем старые данные (строка 3 и ниже, только колонки A-L)
    last_row = ws.max_row
    for r in range(3, last_row + 1):
        for col in range(1, 13):
            cell = ws.cell(row=r, column=col)
            if cell.value is not None and not (
                    isinstance(cell.value, str) and cell.value.startswith("=")):
                cell.value = None

    for i, p in enumerate(products):
        row = 3 + i
        ws.cell(row=row, column=BD_NUM,     value=p.get("num")        or (i + 1))
        ws.cell(row=row, column=BD_ARTICLE, value=p.get("article")    or "")
        ws.cell(row=row, column=BD_NAME,    value=p.get("name")       or "")
        ws.cell(row=row, column=BD_UNIT,    value=p.get("unit")       or "")
        ws.cell(row=row, column=BD_KAZNISA, value=p.get("kaznisa")    or None)
        ws.cell(row=row, column=BD_RRTS,    value=p.get("rrts")       or None)
        ws.cell(row=row, column=BD_MRC,     value=p.get("mrc")        or None)
        ws.cell(row=row, column=BD_OPT,     value=p.get("opt")        or None)
        ws.cell(row=row, column=BD_PARTNER, value=p.get("partner")    or None)
        ws.cell(row=row, column=BD_BRAND,   value=p.get("brand")      or "")
        ws.cell(row=row, column=BD_MULT,    value=p.get("multiplicity") or None)
        ws.cell(row=row, column=BD_KAZ_CODE,value=p.get("kaznisa_code") or "")


def _fill_const_sheet(wb: openpyxl.Workbook, constants: Dict):
    """Заполняет лист Const актуальными константами бренда, менеджерами и курсами."""
    if "Const" not in wb.sheetnames:
        return
    ws = wb["Const"]

    brands    = constants.get("brands", [])
    currencies = constants.get("currencies", [])

    managers_full = constants.get("managers_full", [])
    last_row = max(ws.max_row, 2 + max(len(brands), len(managers_full), len(currencies), 1))

    # Очищаем только бренд-константы (H-N) и курсы (V-W) — не трогаем B-E (менеджеры),
    # если у нас нет полных данных
    clear_managers = bool(managers_full)
    for r in range(2, last_row + 1):
        cols_to_clear = list(range(CONST_BRAND, CONST_GP + 1)) + [CONST_CUR_NAME, CONST_CUR_RATE]
        if clear_managers:
            cols_to_clear = list(range(CONST_MANAGER, CONST_GP + 1)) + [CONST_CUR_NAME, CONST_CUR_RATE]
        for col in cols_to_clear:
            cell = ws.cell(row=r, column=col)
            if cell.value is not None and not (
                    isinstance(cell.value, str) and cell.value.startswith("=")):
                cell.value = None

    # Менеджеры (B-E) — только если сервер вернул полные данные
    for i, m in enumerate(managers_full):
        row = 2 + i
        ws.cell(row=row, column=CONST_MANAGER,  value=m.get("full_name", ""))
        ws.cell(row=row, column=CONST_POSITION, value=m.get("position", ""))
        ws.cell(row=row, column=CONST_EMAIL,    value=m.get("email",     ""))
        ws.cell(row=row, column=CONST_PHONE,    value=m.get("phone",     ""))

    # Бренд-константы (H-N)
    for i, b in enumerate(brands):
        row = 2 + i
        ws.cell(row=row, column=CONST_BRAND,    value=b.get("brand", ""))
        ws.cell(row=row, column=CONST_MARGIN,   value=b.get("margin"))
        ws.cell(row=row, column=CONST_LOGISTICS,value=b.get("logistics"))
        ws.cell(row=row, column=CONST_RATE,     value=b.get("rate"))
        ws.cell(row=row, column=CONST_CURRATE,  value=b.get("currency_rate"))
        ws.cell(row=row, column=CONST_NDS,      value=b.get("nds"))
        ws.cell(row=row, column=CONST_GP,       value=b.get("gp"))

    # Курсы валют (V-W)
    for i, c in enumerate(currencies):
        row = 2 + i
        ws.cell(row=row, column=CONST_CUR_NAME, value=c.get("name", ""))
        ws.cell(row=row, column=CONST_CUR_RATE, value=c.get("rate"))

    # ── Список типов расценки в колонке AE (строки 1-8) ──────────────────────
    for idx, label in enumerate(RATE_TYPE_LABELS, start=1):
        ws.cell(row=idx, column=CONST_RATE_LIST_COL, value=label)

    # ── Data validation dropdown в колонке K (Расценка) ──────────────────────
    ae = get_column_letter(CONST_RATE_LIST_COL)  # "AE"
    dv_end_row = max(2 + len(brands), 20)
    rate_dv = DataValidation(
        type="list",
        formula1=f"Const!${ae}$1:${ae}$8",
        allow_blank=True,
        showDropDown=False,
    )
    rate_dv.error       = "Выберите из списка"
    rate_dv.errorTitle  = "Тип расценки"
    rate_dv.prompt      = "Выберите тип расценки"
    rate_dv.promptTitle = "Расценка"
    for old_dv in [dv for dv in ws.data_validations.dataValidation if "K" in str(dv.sqref)]:
        ws.data_validations.dataValidation.remove(old_dv)
    ws.add_data_validation(rate_dv)
    rate_dv.sqref = f"K2:K{dv_end_row}"


def _fill_kp_header(wb: openpyxl.Workbook, manager: str, project: str, client: str):
    """Заполняем шапку коммерческого предложения."""
    if "КП" not in wb.sheetnames:
        return
    kp = wb["КП"]
    try:
        if manager:
            kp["C3"] = manager
        if project:
            kp["F3"] = project
        if client:
            kp["F4"] = client
    except Exception as e:
        print(f"[Excel/КП] header: {e}")


def _shift_row_refs(formula: str, old_итого: int, shift: int) -> str:
    """Shift all row numbers >= old_итого in a formula string by shift."""
    import re as _re
    def _rep(m):
        col_part = m.group(1)
        row_num  = int(m.group(2))
        return col_part + str(row_num + shift if row_num >= old_итого else row_num)
    return _re.sub(r'([A-Za-z]+)(\d+)', _rep, formula)


def _fill_kp_data(wb: openpyxl.Workbook, items: List[Dict], brand_consts: Dict):
    """Заполняет строки данных листа КП.

    НЕ использует insert_rows() — это ломает VBA-модули в .xlsm файлах.
    Вместо этого:
      1. Находим строку "Итого:" динамически (сканируем снизу данных).
      2. Сохраняем весь подвал (Итого, НДС, условия, подпись) как словарь.
      3. Очищаем зону данных + старый подвал.
      4. Пишем данные (только колонки A–I: без КазНИИСА/РРЦ).
      5. Переносим подвал вниз через запись значений (без структурных операций).
      6. Исправляем формулу SUM в строке Итого.
      7. Обновляем ссылку Таблица5 без insert_rows.
    """
    import re as _re
    from copy import copy as _copy
    if "КП" not in wb.sheetnames:
        return
    kp = wb["КП"]

    # ── 1. Найти строку "Итого:" ─────────────────────────────────────────────
    итого_row = None
    for r in range(KP_DATA_START, KP_DATA_START + 2000):
        for col in range(1, 10):
            v = kp.cell(row=r, column=col).value
            if isinstance(v, str) and v.strip().lower().startswith("итого"):
                итого_row = r
                break
        if итого_row:
            break
    if not итого_row:
        итого_row = KP_DATA_MAX + 1   # запасной вариант

    # ── 2. Сохранить подвал (до 80 строк начиная с Итого) ──────────────────
    FOOTER_ROWS = 80
    footer: dict = {}   # {offset_from_итого: {col: value}}
    for offset in range(FOOTER_ROWS):
        r = итого_row + offset
        row_data = {}
        for col in range(1, 20):
            v = kp.cell(row=r, column=col).value
            if v is not None:
                row_data[col] = v
        if row_data:
            footer[offset] = row_data

    # ── 3. Снять calculatedColumnFormula из Таблица5 ────────────────────────
    kp_table = kp.tables.get("Таблица5")
    if kp_table:
        for tc in kp_table.tableColumns:
            tc.calculatedColumnFormula = None
        if kp_table.autoFilter:
            kp_table.autoFilter.filterColumn = []

    # ── 3б. Сохранить merge-диапазоны из зоны данных/подвала ─────────────────
    # Они мешают записи значений — нужно разъединить, потом пересоздать.
    clear_end = итого_row + FOOTER_ROWS + 5
    footer_merges = []   # (offset_from_итого, min_col, max_col)
    data_merges_to_undo = []   # строковые диапазоны для unmerge
    for mr in list(kp.merged_cells.ranges):
        if mr.min_row >= KP_DATA_START and mr.max_row < clear_end:
            data_merges_to_undo.append(str(mr))
            # If inside footer zone, remember for relocation
            if mr.min_row >= итого_row:
                footer_merges.append((
                    mr.min_row - итого_row,  # offset
                    mr.min_col, mr.max_col,
                    mr.min_row, mr.max_row,  # orig rows (for multi-row spans)
                ))
    for rng in data_merges_to_undo:
        try:
            kp.unmerge_cells(rng)
        except Exception:
            pass

    # ── 4. Очистить зону данных + старого подвала ───────────────────────────
    for r in range(KP_DATA_START, clear_end):
        kp.row_dimensions[r].hidden = False
        for col in range(1, 20):
            cell = kp.cell(row=r, column=col)
            # Skip MergedCell slaves (read-only), only clear master cells
            try:
                if cell.value is not None:
                    cell.value = None
            except (TypeError, AttributeError):
                pass

    # ── 5. Записать строки данных (колонки A–I, без КазНИИСА/РРЦ) ──────────
    # Стили уже присутствуют в шаблоне до строки 1012 (расширено excel_cache.py).
    last_data_row = KP_DATA_START - 1
    for i, item in enumerate(items):
        row  = KP_DATA_START + i
        if item.get("is_heading"):
            # Heading row: write name to C column only + bold styling
            h_name    = item.get("name_raw", "")
            h_article = item.get("article_raw", "") or ""
            kp.cell(row=row, column=KP_NAME,    value=h_name    or None)
            kp.cell(row=row, column=KP_ARTICLE, value=h_article or None)
            _apply_heading_style(kp, row, max_col=14)
            last_data_row = row
            continue
        bm   = item.get("best_match") or {}

        article  = bm.get("article", "") or item.get("article_raw", "")
        name     = bm.get("name",    "") or item.get("name_raw",    "")
        brand    = bm.get("brand",   "")
        unit     = bm.get("unit", "") if bm else item.get("unit", "шт.")
        qty      = float(item.get("qty", 1) or 1)
        comment  = item.get("comment",  "") or ""
        delivery = item.get("delivery", "") or ""

        price_kp = float(item.get("_computed_kp_price") or 0)
        sum_kp   = float(item.get("_computed_kp_sum")   or 0)

        kp.cell(row=row, column=KP_BRAND,    value=brand    or None)
        kp.cell(row=row, column=KP_ARTICLE,  value=article  or None)
        kp.cell(row=row, column=KP_NAME,     value=name     or None)
        kp.cell(row=row, column=KP_UNIT,     value=unit     or None)
        kp.cell(row=row, column=KP_QTY,      value=qty)
        kp.cell(row=row, column=KP_PRICE_KP, value=price_kp or None)
        kp.cell(row=row, column=KP_SUM_KP,   value=sum_kp   or None)
        kp.cell(row=row, column=KP_COMMENT,  value=comment  or None)
        kp.cell(row=row, column=KP_DELIVERY, value=delivery or None)
        last_data_row = row

    # ── 6. Перенести подвал на новую позицию ────────────────────────────────
    new_итого_row = last_data_row + 2   # пустая строка-разделитель
    shift         = new_итого_row - итого_row

    for offset, row_data in sorted(footer.items()):
        new_r = new_итого_row + offset
        for col, val in row_data.items():
            if isinstance(val, str) and val.startswith("=") and shift != 0:
                val = _shift_row_refs(val, итого_row, shift)
            kp.cell(row=new_r, column=col).value = val

    # ── 7. Исправить формулу SUM в строке Итого ─────────────────────────────
    # Ищем ячейку с формулой суммы в строке new_итого_row
    for col in range(1, 15):
        v = kp.cell(row=new_итого_row, column=col).value
        if isinstance(v, str) and v.startswith("="):
            tl = v.lower()
            if "сумм" in tl or "sum" in tl:
                # Заменяем конечную строку диапазона на фактическую последнюю
                fixed = _re.sub(
                    r'([Gg])(\d+)\)',
                    lambda m: m.group(1) + str(last_data_row) + ")",
                    v,
                )
                kp.cell(row=new_итого_row, column=col).value = fixed

    # ── 8. Пересоздать merge-диапазоны в новом месте подвала ────────────────
    if footer_merges:
        shift = new_итого_row - итого_row
        for (offset, min_col, max_col, orig_min_row, orig_max_row) in footer_merges:
            new_min = orig_min_row + shift
            new_max = orig_max_row + shift
            col_min_ltr = openpyxl.utils.get_column_letter(min_col)
            col_max_ltr = openpyxl.utils.get_column_letter(max_col)
            rng = f"{col_min_ltr}{new_min}:{col_max_ltr}{new_max}"
            try:
                kp.merge_cells(rng)
            except Exception:
                pass

    # ── 9. Обновить ссылку Таблица5 (без insert_rows) ───────────────────────
    if kp_table and last_data_row >= KP_DATA_START:
        kp_table.ref = _re.sub(
            r'(\$?[A-Za-z]+\$?)\d+$',
            lambda m: m.group(1) + str(last_data_row),
            kp_table.ref,
        )



def _extend_sheet_styles(ws, n_items: int, data_start: int = 2) -> None:
    """
    Копирует стили из последней стилизованной строки вниз до строки (data_start + n_items).
    Нужно для шаблонов у которых стили есть только до определённой строки.
    Не трогает значения и формулы — только border/font/fill/alignment/number_format.
    """
    from copy import copy as _copy

    need_row = data_start + n_items        # последняя строка данных
    # Найти последнюю строку со стилями
    last_styled = data_start
    for r in range(data_start, need_row + 50):
        row_styled = False
        for col in range(1, 15):
            if ws.cell(row=r, column=col).has_style:
                row_styled = True
                break
        if row_styled:
            last_styled = r
        elif r > last_styled + 3:
            break   # 3 пустые подряд — конец зоны стилей

    if last_styled >= need_row:
        return   # стилей уже достаточно

    # Читаем образец стиля из последней стилизованной строки
    src_styles = {}
    for col in range(1, 15):
        cell = ws.cell(row=last_styled, column=col)
        if cell.has_style:
            src_styles[col] = (
                cell.number_format,
                _copy(cell.font),
                _copy(cell.border),
                _copy(cell.fill),
                _copy(cell.alignment),
            )

    # Применяем стиль к строкам за границей
    for row in range(last_styled + 1, need_row + 1):
        for col, style_tuple in src_styles.items():
            nfmt, font, border, fill, alignment = style_tuple
            dst = ws.cell(row=row, column=col)
            dst.number_format = nfmt
            try:
                dst.font      = _copy(font)
                dst.border    = _copy(border)
                dst.fill      = _copy(fill)
                dst.alignment = _copy(alignment)
            except Exception:
                pass


def _extend_kp_styles(wb, n_items: int) -> None:
    """
    Расширяет стили листа КП и обновляет Таблица5.ref если данных больше
    чем строк в шаблоне.  Идентичен логике excel_cache._extend_kp_table,
    но без переноса подвала (это делает _fill_kp_data).
    """
    from copy import copy as _copy
    import re as _re

    if "КП" not in wb.sheetnames:
        return
    kp = wb["КП"]

    kp_table = kp.tables.get("Таблица5")
    if not kp_table:
        # нет таблицы — просто расширяем стили
        _extend_sheet_styles(kp, n_items, data_start=KP_DATA_START)
        return

    # Разбираем ref таблицы, например "A12:N500"
    m = _re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', kp_table.ref, _re.IGNORECASE)
    if not m:
        return

    table_header = int(m.group(2))   # 12
    current_end  = int(m.group(4))   # 500
    need_end     = table_header + n_items + 10  # запас

    if current_end >= need_end:
        return   # уже достаточно

    # Читаем стили из последней строки таблицы
    src_styles = {}
    for col in range(1, 15):
        cell = kp.cell(row=current_end, column=col)
        nfmt = cell.number_format
        if cell.has_style:
            src_styles[col] = (
                nfmt,
                _copy(cell.font),
                _copy(cell.border),
                _copy(cell.fill),
                _copy(cell.alignment),
            )

    # Снять calculatedColumnFormula и autoFilter чтобы не было #REF!
    for tc in kp_table.tableColumns:
        tc.calculatedColumnFormula = None
    if kp_table.autoFilter:
        kp_table.autoFilter.filterColumn = []

    # Применить стили к новым строкам
    for row in range(current_end + 1, need_end + 1):
        for col, style_tuple in src_styles.items():
            nfmt, font, border, fill, alignment = style_tuple
            dst = kp.cell(row=row, column=col)
            dst.number_format = nfmt
            try:
                dst.font      = _copy(font)
                dst.border    = _copy(border)
                dst.fill      = _copy(fill)
                dst.alignment = _copy(alignment)
            except Exception:
                pass

    # Обновить ref таблицы
    kp_table.ref = _re.sub(
        r'(\$?[A-Za-z]+\$?)\d+$',
        lambda mm: mm.group(1) + str(need_end),
        kp_table.ref,
    )



def _extend_wv_formulas(ws, last_data_row: int) -> None:
    """
    Копирует формулы из последней строки шаблона WV 4.0 в строки за её пределами.
    Обрабатывает:
      - col 6  (F) — формула кратности (обычная строка-формула)
      - cols 8-12 (H-L) — ArrayFormula с ценами из БД
    Пропускает ячейки которые уже заполнены явными значениями.
    """
    from openpyxl.worksheet.formula import ArrayFormula

    # Найти последнюю строку с ArrayFormula в col 8 (цены)
    last_formula_row = 0
    for r in range(2, last_data_row + 50):
        if isinstance(ws.cell(row=r, column=8).value, ArrayFormula):
            last_formula_row = r
        elif last_formula_row > 0 and r > last_formula_row + 3:
            break

    if last_formula_row == 0 or last_formula_row >= last_data_row:
        return  # нечего расширять

    src_row     = last_formula_row
    src_row_str = str(src_row)

    # Только «формульные» колонки которые мы НЕ пишем явно
    formula_cols = [6, 8, 9, 10, 11, 12]

    for dst_row in range(last_formula_row + 1, last_data_row + 1):
        dst_row_str = str(dst_row)
        for col in formula_cols:
            dst_cell = ws.cell(row=dst_row, column=col)
            if dst_cell.value is not None:
                continue   # явное значение — не трогаем

            src_val = ws.cell(row=src_row, column=col).value
            if src_val is None:
                continue

            if isinstance(src_val, ArrayFormula):
                new_ref  = src_val.ref.replace(src_row_str, dst_row_str)
                new_text = src_val.text.replace(src_row_str, dst_row_str)
                dst_cell.value = ArrayFormula(new_ref, new_text)
            elif isinstance(src_val, str) and src_val.startswith("="):
                dst_cell.value = src_val.replace(src_row_str, dst_row_str)



def _safe_sheet_name(name: str, idx: int, existing: list) -> str:
    """Return a valid Excel sheet name (max 31 chars, no special chars, unique)."""
    import re as _re2
    safe = _re2.sub(r'[\\/?*\[\]:]', '', str(name))[:31] or f"Sheet{idx+1}"
    if safe not in existing:
        return safe
    base = safe[:28]
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def _restore_missing_rels(tpl_path: str, out_path: str) -> None:
    """
    Restores worksheet relationship files that openpyxl silently drops on save.

    Handles any number of project sheets by matching rels by sheet NAME
    (not file number), so КП rels are always applied to the correct sheet
    even when extra WV sheets shift the sheet numbering.

    Also:
      - Copies extra files from template (drawings, slicers, printerSettings…)
      - Strips dangling externalLinks and vbaProject.bin references
    """
    import zipfile, io as _io, re as _re

    # ── helpers ──────────────────────────────────────────────────────────────
    def _abs_target(target: str) -> str:
        if target.startswith("../"):
            return "/xl/" + target[3:]
        return target

    def _target_file(target: str) -> str:
        return target.rstrip("/").split("/")[-1]

    def _parse_rels(xml: str) -> list:
        out = []
        for m in _re.finditer(r'<Relationship\b[^>]*/>', xml):
            tag  = m.group()
            id_m = _re.search(r'Id="([^"]+)"', tag)
            tp_m = _re.search(r'Type="([^"]+)"', tag)
            tg_m = _re.search(r'Target="([^"]+)"', tag)
            if id_m and tp_m and tg_m:
                out.append((tp_m.group(1), id_m.group(1), _abs_target(tg_m.group(1))))
        return out

    def _rel_target(abs_t: str) -> str:
        if abs_t.startswith("/xl/"):
            return "../" + abs_t[4:]
        return abs_t

    def _merge_rels(saved_xml: str, tpl_rels: list) -> str:
        """Merge template rels into saved_xml, avoiding duplicates."""
        existing_targets = set(
            _target_file(tg)
            for tg in _re.findall(r'Target="([^"]+)"', saved_xml)
        )
        existing_rids = set(_re.findall(r'Id="(rId\d+)"', saved_xml))
        max_rid = max(
            (int(r[3:]) for r in existing_rids if r[3:].isdigit()),
            default=0,
        )
        def _next_rid():
            nonlocal max_rid
            max_rid += 1
            return f"rId{max_rid}"

        inserts = []
        for (rel_type, rid, abs_target) in tpl_rels:
            fname = _target_file(abs_target)
            rel_t = _rel_target(abs_target)
            if "vmlDrawing" in rel_type:
                continue
            if fname not in existing_targets:
                if rel_type.endswith("/drawing"):
                    def _fix_drawing(m, correct_rel=rel_t):
                        tag    = m.group()
                        type_m = _re.search(r'Type="([^"]+)"', tag)
                        if not type_m:
                            return tag
                        if not type_m.group(1).endswith("/drawing"):
                            return tag
                        return _re.sub(r'Target="[^"]+"', f'Target="{correct_rel}"', tag)
                    new_xml = _re.sub(r'<Relationship\b[^>]*/>', _fix_drawing, saved_xml)
                    if new_xml != saved_xml:
                        saved_xml = new_xml
                        existing_targets.add(fname)
                        continue
                use_rid = rid if rid not in existing_rids else _next_rid()
                inserts.append(
                    f'<Relationship Id="{use_rid}" Type="{rel_type}" Target="{rel_t}"/>',
                )
                existing_targets.add(fname)
                existing_rids.add(use_rid)

        if inserts:
            saved_xml = saved_xml.replace("</Relationships>",
                                          "".join(inserts) + "</Relationships>")
        return saved_xml

    def _ws_name_to_file(zip_obj):
        """Returns {sheet_name: 'xl/worksheets/sheetN.xml'} by parsing workbook.xml."""
        try:
            wb_x   = zip_obj.read("xl/workbook.xml").decode("utf-8", errors="replace")
            rels_x = zip_obj.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="replace")
            name_rid = {}
            for m in _re.finditer(r'<sheet\b([^>]*)/?>', wb_x):
                nm = _re.search(r'\bname="([^"]*)"', m.group(1))
                ri = _re.search(r'r:id="([^"]*)"', m.group(1))
                if nm and ri:
                    name_rid[nm.group(1)] = ri.group(1)
            rid_file = {}
            for m in _re.finditer(r'<Relationship\b[^>]*/>', rels_x):
                t   = m.group()
                id_ = _re.search(r'\bId="([^"]+)"', t)
                tp_ = _re.search(r'\bType="([^"]+)"', t)
                tg_ = _re.search(r'\bTarget="([^"]+)"', t)
                if id_ and tp_ and tg_ and "worksheet" in tp_.group(1):
                    tgt = tg_.group(1)
                    if not tgt.startswith("xl/"):
                        tgt = "xl/worksheets/" + tgt.split("/")[-1]
                    rid_file[id_.group(1)] = tgt
            return {n: rid_file[r] for n, r in name_rid.items() if r in rid_file}
        except Exception:
            return {}

    # ── Collect template data ─────────────────────────────────────────────────
    try:
        with zipfile.ZipFile(tpl_path, "r") as ztpl:
            tpl_files = set(ztpl.namelist())

            # Sheet rels by filename
            tpl_sheet_rels: dict = {}
            for fn in tpl_files:
                if fn.startswith("xl/worksheets/_rels/") and fn.endswith(".rels"):
                    tpl_sheet_rels[fn] = _parse_rels(
                        ztpl.read(fn).decode("utf-8", errors="replace")
                    )

            # Sheet name → rels mapping
            tpl_name_to_file = _ws_name_to_file(ztpl)
            tpl_name_to_rels: dict = {}
            for sname, sfile in tpl_name_to_file.items():
                rels_fn = sfile.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels"
                if rels_fn in tpl_sheet_rels:
                    tpl_name_to_rels[sname] = tpl_sheet_rels[rels_fn]

            # Extra binary/xml files to copy from template
            _is_xlsx = out_path.lower().endswith(".xlsx")
            _extra_prefixes = (
                "xl/drawings/", "xl/media/", "xl/printerSettings/", "xl/tables/",
            ) if _is_xlsx else (
                "xl/drawings/", "xl/slicers/", "xl/slicerCaches/",
                "xl/media/", "xl/printerSettings/", "xl/tables/",
            )
            tpl_extras: dict = {}
            for fn in tpl_files:
                if any(fn.startswith(p) for p in _extra_prefixes):
                    tpl_extras[fn] = ztpl.read(fn)

        # Build out_rels_merge_map: output rels filename → template rels
        # Match by sheet NAME so renumbering (sheet2→sheet3 etc.) is handled.
        with zipfile.ZipFile(out_path, "r") as _ztmp:
            out_name_to_file = _ws_name_to_file(_ztmp)

        out_rels_merge_map: dict = {}
        for sname, sfile in out_name_to_file.items():
            if sname not in tpl_name_to_rels:
                continue
            out_rels_fn = sfile.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels"
            out_rels_merge_map[out_rels_fn] = tpl_name_to_rels[sname]

        # Handle renamed "WV 4.0" sheet: generate_excel_multi renames it to
        # the project name, so name-matching above misses it.
        # Apply "WV 4.0" template rels to the first non-КП output sheet.
        _WV_TPL_NAME = "WV 4.0"
        if _WV_TPL_NAME in tpl_name_to_rels and _WV_TPL_NAME not in out_name_to_file:
            for _sname, _sfile in out_name_to_file.items():
                if _sname == "КП":
                    continue
                _out_rels_fn = _sfile.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels"
                if _out_rels_fn not in out_rels_merge_map:
                    out_rels_merge_map[_out_rels_fn] = tpl_name_to_rels[_WV_TPL_NAME]
                break

        # ── Rewrite ZIP ───────────────────────────────────────────────────────
        with open(out_path, "rb") as fh:
            raw = fh.read()

        in_buf  = _io.BytesIO(raw)
        out_buf = _io.BytesIO()

        with zipfile.ZipFile(in_buf, "r") as zin:
            existing_saved = set(zin.namelist())
            ct_xml_orig = ""

            with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)

                    # Drop external link files
                    if item.filename.startswith("xl/externalLinks/"):
                        continue

                    # Force-replace drawing XML with template version:
                    # openpyxl strips slicer controls from drawings and
                    # uses absolute Target paths in drawing rels.
                    # Also force-replace table XML (template has correct
                    # structure; we will strip calculatedColumnFormulas below).
                    _FORCE_FROM_TPL = (
                        item.filename.startswith("xl/drawings/") or
                        item.filename.startswith("xl/tables/")
                    )
                    if _FORCE_FROM_TPL and item.filename in tpl_extras:
                        data = tpl_extras[item.filename]
                        # Strip calculatedColumnFormula from table files
                        if item.filename.startswith("xl/tables/"):
                            tbl_xml = data.decode("utf-8", errors="replace")
                            tbl_xml = _re.sub(
                                r'<calculatedColumnFormula[^<]*</calculatedColumnFormula>',
                                "", tbl_xml,
                            )
                            data = tbl_xml.encode("utf-8")


                    if item.filename in out_rels_merge_map:
                        xml = data.decode("utf-8", errors="replace")
                        _tpl_rels = out_rels_merge_map[item.filename]
                        if _is_xlsx:
                            _tpl_rels = [(rt, rid, at) for rt, rid, at in _tpl_rels
                                         if "slicer" not in rt.lower()]
                        xml  = _merge_rels(xml, _tpl_rels)
                        data = xml.encode("utf-8")

                    elif item.filename == "xl/workbook.xml":
                        xml = data.decode("utf-8", errors="replace")
                        # Strip external references section
                        xml = _re.sub(
                            r'<externalReferences\b[^>]*>.*?</externalReferences>',
                            "", xml, flags=_re.DOTALL,
                        )
                        # Strip definedNames that reference broken/external data:
                        # #REF!, [N]ExternalBook, #N/A, #NAME? values
                        def _strip_bad_dn(m):
                            val = m.group(1)
                            if (
                                "#REF!" in val or "#N/A" in val or
                                "#NAME?" in val or
                                _re.search(r"\[\d+\]", val)  # [1]ExternalBook
                            ):
                                return ""
                            return m.group(0)
                        xml = _re.sub(
                            r'<definedName\b[^>]*>([^<]*)</definedName>',
                            _strip_bad_dn, xml,
                        )
                        data = xml.encode("utf-8")

                    elif item.filename == "xl/_rels/workbook.xml.rels":
                        xml = data.decode("utf-8", errors="replace")
                        # Strip dangling externalLinks
                        xml = _re.sub(
                            r'<Relationship\b[^>]*externalLink[^>]*/>',
                            "", xml,
                        )
                        # Strip dangling vbaProject.bin ref added by openpyxl keep_vba=True
                        xml = _re.sub(
                            r'<Relationship\b[^>]*vbaProject[^>]*/>',
                            "", xml,
                        )
                        data = xml.encode("utf-8")

                    elif item.filename == "[Content_Types].xml":
                        ct_xml_orig = data.decode("utf-8", errors="replace")
                        continue  # re-written at end

                    zout.writestr(item, data)

                # Write template extra files that are missing from output
                for fn, fdata in tpl_extras.items():
                    if fn not in existing_saved:
                        if _is_xlsx and any(
                            k in fn for k in ("slicer", "Slicer")
                        ):
                            continue
                        zout.writestr(fn, fdata)
                        print(f"[ws_rels] restored {fn} from template")

                # Create missing sheet rels files (keyed by OUTPUT filename)
                for out_rels_fn, tpl_rels in out_rels_merge_map.items():
                    if out_rels_fn not in existing_saved:
                        needed = [
                            (rt, rid, at) for (rt, rid, at) in tpl_rels
                            if "vmlDrawing" not in rt
                            and (not _is_xlsx or "slicer" not in rt.lower())
                        ]
                        if needed:
                            inserts = [
                                f'<Relationship Id="{rid}" Type="{rt}" Target="{_rel_target(at)}"/>'
                                for (rt, rid, at) in needed
                            ]
                            xml = (
                                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                + "".join(inserts) + "</Relationships>"
                            )
                            zout.writestr(out_rels_fn, xml.encode("utf-8"))
                            print(f"[ws_rels] created missing {out_rels_fn}")

                # Re-write [Content_Types].xml: strip externalLink overrides,
                # register any newly added template extras
                ct_xml = ct_xml_orig
                ct_xml = _re.sub(
                    r'<Override[^>]*externalLink[^>]*/>', "", ct_xml
                )
                for fn, fdata in tpl_extras.items():
                    if fn not in existing_saved:
                        if _is_xlsx and any(k in fn for k in ("slicer", "Slicer")):
                            continue
                        part = "/" + fn
                        if part not in ct_xml:
                            ext = fn.rsplit(".", 1)[-1].lower()
                            ct_map = {
                                "xml":  "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
                                "bin":  "application/vnd.ms-office.activeX+xml",
                                "rels": "application/vnd.openxmlformats-package.relationships+xml",
                                "png":  "image/png",
                                "jpeg": "image/jpeg",
                                "jpg":  "image/jpeg",
                                "emf":  "image/x-emf",
                            }
                            # Use specific content types for known subdirs
                            if "drawings" in fn:
                                ct = "application/vnd.openxmlformats-officedocument.drawing+xml"
                            elif "slicers" in fn:
                                ct = "application/vnd.ms-excel.slicer+xml"
                            elif "slicerCaches" in fn:
                                ct = "application/vnd.ms-excel.slicerCache+xml"
                            elif "printerSettings" in fn:
                                ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.printerSettings"
                            else:
                                ct = ct_map.get(ext, "application/octet-stream")
                            if not fn.endswith(".rels"):
                                ct_xml = ct_xml.replace(
                                    "</Types>",
                                    f'<Override PartName="{part}" ContentType="{ct}"/></Types>',
                                )
                                print(f"[ws_rels] registered {part} in [Content_Types].xml")
                zout.writestr("[Content_Types].xml", ct_xml.encode("utf-8"))

        with open(out_path, "wb") as fh:
            fh.write(out_buf.getvalue())

        print(f"[ws_rels] done: {out_path}")

    except Exception as exc:
        import traceback
        print(f"[ws_rels] failed: {exc}")
        traceback.print_exc()

def generate_excel(
    items: List[Dict],
    output_path: str,
    constants: Optional[Dict] = None,
    products: Optional[List[Dict]] = None,
    brand_consts: Optional[Dict] = None,
    project_name: str = "",
    client_name: str = "",
    manager_name: str = "",
    base_template_path: str = "",
) -> str:
    """
    Сохраняет результат в .xlsm на основе шаблона со всеми макросами.

    items              — список позиций с best_match, status, qty, _user_price, …
    constants          — ответ api.get_constants() (brands, managers, currencies)
    products           — ответ api.get_all_products() (все товары для листа БД)
    brand_consts       — {BRAND_UPPER: {margin, logistics, …}} (уже построен в preview_page)
    base_template_path — путь к скачанному с сервера файлу (уже содержит БД и Const);
                         если передан — пропускаем _fill_bd_sheet и _fill_const_sheet.
    """
    out_path = output_path
    if not out_path.lower().endswith(".xlsm"):
        out_path = os.path.splitext(out_path)[0] + ".xlsm"

    # Определяем источник шаблона: серверный кэш или локальный файл
    if base_template_path and os.path.isfile(base_template_path):
        tpl = base_template_path
        _skip_db_const = True
    else:
        tpl = _template_path()
        _skip_db_const = False

    if not tpl:
        raise FileNotFoundError(
            "Шаблон WV_template.xlsm не найден. Поместите его в client/assets/ "
            "и пересоберите .exe (или скопируйте рядом с APSParser.exe в папку assets)."
        )

    shutil.copyfile(tpl, out_path)
    wb = openpyxl.load_workbook(out_path, keep_vba=True, data_only=False)

    if "WV 4.0" not in wb.sheetnames:
        raise ValueError("В шаблоне отсутствует лист 'WV 4.0'")

    ws = wb["WV 4.0"]

    # Расширяем стили листов под фактическое количество позиций
    _extend_sheet_styles(ws, len(items), data_start=2)
    _extend_kp_styles(wb, len(items))

    if not _skip_db_const:
        # 1. Обновляем лист БД актуальными данными с сервера
        if products:
            try:
                _fill_bd_sheet(wb, products)
            except Exception as e:
                print(f"[Excel/БД] {e}")

        # 2. Обновляем лист Const
        if constants:
            try:
                _fill_const_sheet(wb, constants)
            except Exception as e:
                print(f"[Excel/Const] {e}")
    else:
        print("[Excel] Using server-side base template — skipping БД/Const fill")

    # 3. Заполняем лист WV 4.0 (только вводные колонки)
    # Filter out section-header rows before writing to Excel — they have no
    # article/price data and would corrupt row numbering and formula ranges.
    excel_items = items  # headings included — written as section dividers

    _clear_input_rows(ws, start_row=2, end_row=max(465, 2 + len(excel_items)))

    for i, item in enumerate(excel_items):
        row = 2 + i
        if item.get("is_heading"):
            # Write heading name to C, article to B, kaznisa to L
            h_name    = item.get("name_raw", "")
            h_article = item.get("article_raw", "") or ""
            h_kaz     = item.get("kaznisa_code_raw", "") or ""
            ws.cell(row=row, column=WV_NAME,     value=h_name    or None)
            ws.cell(row=row, column=WV_ARTICLE,  value=h_article or None)
            ws.cell(row=row, column=WV_KAZNIISA, value=h_kaz     or None)
            _apply_heading_style(ws, row)
            continue
        bm      = item.get("best_match") or {}
        brand   = bm.get("brand") or ""
        article = bm.get("article") or item.get("article_raw") or ""
        qty     = item.get("qty", 1)

        ws.cell(row=row, column=WV_BRAND,   value=brand)
        ws.cell(row=row, column=WV_ARTICLE, value=article)
        ws.cell(row=row, column=WV_QTY,     value=qty)

        # Записываем наименование и единицу явно: для строк за пределами шаблонных
        # VLOOKUP-формул данные не появятся автоматически.
        wv_name = bm.get("name", "") or item.get("name_raw", "")
        wv_unit = bm.get("unit", "") or item.get("unit", "")
        if wv_name:
            ws.cell(row=row, column=WV_NAME, value=wv_name)
        if wv_unit:
            ws.cell(row=row, column=WV_UNIT, value=wv_unit)

        # Колонка G WV 4.0 = базовая константа (до умножения на НДС/лог/маржу).
        # Заполняется для ВСЕХ строк — это гарантирует что формула WV 4.0
        # вычисляет ту же самую Цена КП, что и Python (_computed_kp_price).
        # Важно: VBA Worksheet_SelectionChange копирует цены WV 4.0 → КП;
        # без явного G формула WV 4.0 использует другой маппинг rate→поле,
        # и цены расходятся с preview.
        # Приоритет записи в G:
        #   1. _user_const_price — пользователь ввёл «константу цены» вручную
        #   2. _user_seb_price   — пользователь задал Цена себес (обратный пересчёт)
        #   3. _user_price       — пользователь задал Цена КП напрямую
        #   4. _computed_kp_price — Python-расчёт (обратный пересчёт из итоговой КП)
        _wv_brand   = (bm.get("brand") or "").upper()
        _wv_bc      = (brand_consts or {}).get(_wv_brand, {})
        _wv_nds     = float(_wv_bc.get("nds",           1.0) or 1.0)
        _wv_lo      = float(_wv_bc.get("logistics",     1.0) or 1.0)
        _wv_cur     = float(_wv_bc.get("currency_rate", 1.0) or 1.0)
        _wv_mg      = float(_wv_bc.get("margin",        1.0) or 1.0)
        _wv_denom_s = _wv_nds * _wv_lo * _wv_cur          # seb = G × denom_s
        _wv_denom_k = _wv_denom_s * _wv_mg                 # kp  = G × denom_k
        try:
            if item.get("_user_const_price") is not None:
                # Константа задана напрямую — это уже и есть G
                ws.cell(row=row, column=WV_CONST_PRC, value=float(item["_user_const_price"]))
            elif item.get("_user_seb_price") is not None:
                # Пользователь задал Цена себес: G = seb / denom_s
                g = float(item["_user_seb_price"]) / _wv_denom_s if _wv_denom_s else float(item["_user_seb_price"])
                ws.cell(row=row, column=WV_CONST_PRC, value=g)
            elif item.get("_user_edited") and item.get("_user_price") is not None:
                # Пользователь задал Цена КП: G = kp / denom_k
                g = float(item["_user_price"]) / _wv_denom_k if _wv_denom_k else float(item["_user_price"])
                ws.cell(row=row, column=WV_CONST_PRC, value=g)
            else:
                # Нередактированная позиция: используем Python-вычисленную Цена КП.
                # G = kp / denom_k → формула WV 4.0 даст ROUNDUP(G×denom_k,0) = kp.

                # Это устраняет расхождение маппинга rate→поле между Python и WV 4.0.
                kp_price = float(item.get("_computed_kp_price") or 0)
                if kp_price and _wv_denom_k:
                    g = kp_price / _wv_denom_k
                    ws.cell(row=row, column=WV_CONST_PRC, value=g)
        except (TypeError, ValueError):
            pass

        comment  = item.get("comment")  or ""
        delivery = item.get("delivery") or ""
        if comment:
            ws.cell(row=row, column=WV_COMMENT,  value=comment)
        if delivery:
            ws.cell(row=row, column=WV_DELIVERY, value=delivery)

    # Расширяем формулы WV для строк за пределами шаблона (цены, кратность)
    if len(excel_items) > 0:
        _extend_wv_formulas(ws, 2 + len(excel_items) - 1)

    # 4. Заполняем шапку и данные листа КП
    try:
        _fill_kp_header(wb,
                        manager=manager_name,
                        project=project_name,
                        client=client_name)
    except Exception as e:
        print(f"[Excel/КП header] {e}")

    try:
        _fill_kp_data(wb, items, brand_consts or {})
    except Exception as e:
        print(f"[Excel/КП data] {e}")

    # 5. Сохраняем файл
    wb.save(out_path)
    _inject_x14_dv(out_path)   # восстанавливаем x14:DV в WV 4.0
    _restore_missing_rels(tpl, out_path)  # восстанавливаем ctrlProp/drawing rels
    return out_path

def generate_excel_multi(
    projects: list,
    output_path: str,
    constants: Optional[Dict] = None,
    products: Optional[List[Dict]] = None,
    base_template_path: str = "",
) -> str:
    """
    Build an .xlsm starting from an exact template copy:
      - Template KP sheet preserved exactly (logo, letterhead rows 1-12)
      - Per-project WV sheets: project 1 reuses template WV 4.0 (renamed),
        projects 2+ get new sheets with matching column structure
      - KP TABLE formulas cleared; static data written from row 13
      - _restore_missing_rels restores logo/slicers/drawing dropped by openpyxl
    """
    import shutil as _shutil
    from openpyxl.styles import Border, Side

    out_path = output_path
    if out_path.lower().endswith(".xlsx"):
        out_path = out_path[:-5] + ".xlsm"
    elif not out_path.lower().endswith(".xlsm"):
        out_path = os.path.splitext(out_path)[0] + ".xlsm"

    tpl = _template_path()

    _shutil.copyfile(tpl, out_path)
    wb = openpyxl.load_workbook(out_path, keep_vba=True, data_only=False)
    if hasattr(wb, "_external_links"):
        wb._external_links = []

    wv_tpl_name = "WV 4.0" if "WV 4.0" in wb.sheetnames else wb.sheetnames[0]
    wv_first = wb[wv_tpl_name]

    wv_col_widths: dict = {}
    for _cl, _cd in wv_first.column_dimensions.items():
        if _cd.width:
            wv_col_widths[_cl] = _cd.width
    wv_hdr_height = wv_first.row_dimensions[1].height or 22

    if projects:
        pname0 = projects[0].get("name", "Project_1")
        sname0 = _safe_sheet_name(
            pname0, 0,
            [s for s in wb.sheetnames if s not in ("КП", wv_tpl_name)],
        )
        wv_first.title = sname0

    if wv_first.max_row and wv_first.max_row > 1:
        wv_first.delete_rows(2, wv_first.max_row - 1)

    THIN     = Side(border_style="thin")
    DATA_BDR = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    NUM_FMT  = "#,##0.00"
    CTR_ALN  = Alignment(horizontal="center",  vertical="center")
    WRAP_ALN = Alignment(horizontal="left",    vertical="center", wrap_text=True)
    LEFT_ALN = Alignment(horizontal="left",    vertical="center")
    HDR_FILL = PatternFill("solid", fgColor="1F3864")
    HDR_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=9)
    HDR_ALN  = Alignment(horizontal="center",  vertical="center", wrap_text=True)
    SEC_FILL = PatternFill("solid", fgColor="17375E")
    SEC_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=9)

    WV_N       = 14
    WV_HEADERS = [
        "Бренд", "Артикул", "Наименование",
        "Ед. изм.", "Кол-во",
        "Кратность", "Константа цена",
        "Цена себес", "Сумма себес",
        "Цена КП", "Сумма КП",
        "Код КазНИИСА",
        "Комментарии", "Срок поставки",
    ]
    WV_ALNS   = [
        LEFT_ALN, LEFT_ALN, WRAP_ALN, CTR_ALN, CTR_ALN,
        CTR_ALN,  CTR_ALN,  CTR_ALN,  CTR_ALN, CTR_ALN,
        CTR_ALN,  LEFT_ALN, WRAP_ALN, LEFT_ALN,
    ]
    WV_PRICE_COLS = {7, 8, 9, 10, 11}

    def _write_wv_data(ws, items_list):
        data_row = 2
        for item in items_list:
            is_hdg = (item.get("status") == "heading") or item.get("is_heading")
            if is_hdg:
                ws.cell(row=data_row, column=1, value=item.get("name_raw", ""))
                try:
                    ws.merge_cells(start_row=data_row, start_column=1,
                                   end_row=data_row, end_column=WV_N)
                except Exception:
                    pass
                for ci2 in range(1, WV_N + 1):
                    try:
                        c           = ws.cell(row=data_row, column=ci2)
                        c.fill      = SEC_FILL
                        c.font      = SEC_FONT
                        c.alignment = LEFT_ALN
                    except Exception:
                        pass
                ws.row_dimensions[data_row].height = 20
                data_row += 1
                continue

            bm  = item.get("best_match") or {}
            qty = float(item.get("qty", 1) or 1)
            kp_price = float(item.get("_computed_kp_price") or 0) or None
            kp_sum   = float(item.get("_computed_kp_sum")   or 0) or None
            seb_price = (
                float(item.get("_user_seb_price")    or 0)
                or float(item.get("_computed_seb_price") or 0)
                or None
            )
            seb_sum = (
                float(item.get("_computed_seb_sum") or 0)
                or ((seb_price * qty) if seb_price else None)
            )
            row_vals = [
                bm.get("brand")   or "",
                bm.get("article") or item.get("article_raw") or "",
                bm.get("name")    or item.get("name_raw")    or "",
                bm.get("unit")    or item.get("unit")        or "",
                qty,
                bm.get("multiplicity") or None,
                item.get("_user_const_price") or None,
                seb_price, seb_sum,
                kp_price,  kp_sum,
                bm.get("kaznisa_code") or item.get("kaznisa_code_raw") or "",
                item.get("comment")  or "",
                item.get("delivery") or "",
            ]
            for ci2, (val, aln) in enumerate(zip(row_vals, WV_ALNS), 1):
                c           = ws.cell(row=data_row, column=ci2, value=val)
                c.alignment = aln
                c.border    = DATA_BDR
                if ci2 in WV_PRICE_COLS:
                    c.number_format = NUM_FMT
            data_row += 1
        ws.auto_filter.ref = f"A1:{get_column_letter(WV_N)}1"

    if projects:
        _write_wv_data(wv_first, projects[0].get("items", []))

    for proj_idx, proj in enumerate(projects[1:], 1):
        pname = proj.get("name", f"Project_{proj_idx + 1}")
        existing_wv = [s for s in wb.sheetnames if s != "КП"]
        sname = _safe_sheet_name(pname, proj_idx, existing_wv)
        kp_idx = (wb.sheetnames.index("КП")
                  if "КП" in wb.sheetnames else len(wb.sheetnames))
        ws = wb.create_sheet(title=sname, index=kp_idx)
        for col_letter, w in wv_col_widths.items():
            ws.column_dimensions[col_letter].width = w
        for ci, (hdr, aln) in enumerate(zip(WV_HEADERS, WV_ALNS), 1):
            cell = ws.cell(row=1, column=ci, value=hdr)
            cell.fill      = HDR_FILL
            cell.font      = HDR_FONT
            cell.alignment = HDR_ALN
        ws.row_dimensions[1].height = wv_hdr_height
        ws.freeze_panes = "A2"
        _write_wv_data(ws, proj.get("items", []))

    kp_ws = wb["КП"]
    # Clear old template formulas from the data range before writing.
    # Rows 13-500 in the template contain IFERROR('WV 4.0'!...) formulas
    # that remain in cells we don't overwrite and cause stale references.
    for _r in range(13, 501):
        for _c in range(1, 15):
            kp_ws.cell(row=_r, column=_c).value = None
    for tbl in kp_ws.tables.values():
        for col in tbl.tableColumns:
            try:
                col.calculatedColumnFormula = None
            except Exception:
                pass

    KP_DATA_START = 13
    KP_N          = 14
    KP_PRICE_COL  = {6, 7, 10, 11, 13, 14}
    KP_ALNS = [
        LEFT_ALN, LEFT_ALN, WRAP_ALN, CTR_ALN, CTR_ALN,
        CTR_ALN,  CTR_ALN,  WRAP_ALN, LEFT_ALN,
        CTR_ALN,  CTR_ALN,  LEFT_ALN, CTR_ALN,  CTR_ALN,
    ]

    kp_row = KP_DATA_START
    for proj in projects:
        # Write project header WITHOUT merging — merged cells inside a
        # table range (A12:N500) cause Excel to discard the entire table.
        kp_ws.cell(row=kp_row, column=1, value=proj.get("name", ""))
        for ci2 in range(1, KP_N + 1):
            try:
                c           = kp_ws.cell(row=kp_row, column=ci2)
                c.fill      = SEC_FILL
                c.font      = SEC_FONT
                c.alignment = LEFT_ALN
            except Exception:
                pass
        kp_ws.row_dimensions[kp_row].height = 20
        kp_row += 1

        for item in proj.get("items", []):
            if item.get("status") == "heading" or item.get("is_heading"):
                continue
            bm        = item.get("best_match") or {}
            qty       = float(item.get("qty", 1) or 1)
            kp_price  = float(item.get("_computed_kp_price") or 0) or None
            kp_sum    = float(item.get("_computed_kp_sum")   or 0) or None
            kaz_price = float(bm.get("kaznisa") or 0) or None
            kaz_sum   = (kaz_price * qty) if kaz_price else None
            rrts_p    = float(bm.get("rrts")    or 0) or None
            rrts_s    = (rrts_p * qty)    if rrts_p    else None
            kp_vals = [
                bm.get("brand")   or "",
                bm.get("article") or item.get("article_raw") or "",
                bm.get("name")    or item.get("name_raw")    or "",
                bm.get("unit")    or item.get("unit")        or "",
                qty,
                kp_price, kp_sum,
                item.get("comment")  or "",
                item.get("delivery") or "",
                kaz_price, kaz_sum,
                bm.get("kaznisa_code") or item.get("kaznisa_code_raw") or "",
                rrts_p, rrts_s,
            ]
            for ci2, (val, aln) in enumerate(zip(kp_vals, KP_ALNS), 1):
                c           = kp_ws.cell(row=kp_row, column=ci2, value=val)
                c.alignment = aln
                c.border    = DATA_BDR
                if ci2 in KP_PRICE_COL:
                    c.number_format = NUM_FMT
            kp_row += 1

    wb.save(out_path)
    _restore_missing_rels(tpl, out_path)
    print(f"[MultiExcel] {len(projects)} project(s) saved to {out_path}")
    return out_path

