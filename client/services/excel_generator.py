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


def _fill_kp_data(wb: openpyxl.Workbook, items: List[Dict], brand_consts: Dict):
    """
    Заполняет строки данных листа КП прямыми значениями.
    Записываются только найденные позиции (status != 'not_found').
    Колонки J, K (КазНИИСА) и M, N (РРЦ в тнг) вычисляем из best_match + курс бренда.
    """
    if "КП" not in wb.sheetnames:
        return
    kp = wb["КП"]

    # Удаляем calculatedColumnFormula из Таблица5 — иначе Excel перетрёт
    # наши записанные значения своими формулами колонки при открытии файла
    kp_table = kp.tables.get("Таблица5")
    if kp_table:
        for tc in kp_table.tableColumns:
            tc.calculatedColumnFormula = None
        # Убираем кешированный фильтр (filterColumn) — он скрывает строки,
        # где Цена/Сумма КП была " " (пробел из формулы).
        # Теперь мы пишем прямые значения — фильтр не нужен.
        if kp_table.autoFilter:
            kp_table.autoFilter.filterColumn = []

    # Снимаем hidden="1" со всех строк диапазона данных.
    # Шаблон хранит кешированное состояние фильтра: строки 15-500 помечены
    # hidden=True (их скрывал autoFilter), поэтому Excel их не показывает
    # даже после того, как мы записали туда значения.
    for r in range(KP_DATA_START, KP_DATA_MAX + 1):
        kp.row_dimensions[r].hidden = False

    # Очищаем старые данные строк
    for r in range(KP_DATA_START, KP_DATA_MAX + 1):
        for col in range(1, 15):          # A-N
            cell = kp.cell(row=r, column=col)
            if cell.value is not None:
                cell.value = None

    found_items = [it for it in items if it.get("status") != "not_found"]

    row = KP_DATA_START
    for item in found_items:
        if row > KP_DATA_MAX:
            break
        bm    = item.get("best_match") or {}
        brand = bm.get("brand", "")
        bc    = brand_consts.get(brand.upper(), {})
        cur_rate = float(bc.get("currency_rate") or 1.0)

        article      = bm.get("article", "") or item.get("article_raw", "")
        name         = bm.get("name", "")    or item.get("name", "")
        unit         = bm.get("unit", "шт.")
        qty          = float(item.get("qty", 1) or 1)
        kaz_code     = bm.get("kaznisa_code", "") or ""
        comment      = item.get("comment", "")  or ""
        delivery     = item.get("delivery", "") or ""

        # Цена КП (из preview или вычисленная)
        price_kp = float(item.get("_computed_kp_price") or 0)
        sum_kp   = float(item.get("_computed_kp_sum")   or 0)
        if not price_kp and qty:
            sum_kp = price_kp * qty

        # КазНИИСА: сырая цена × курс
        raw_kaz   = float(bm.get("kaznisa") or 0)
        price_kaz = math.ceil(raw_kaz * cur_rate) if raw_kaz else 0
        sum_kaz   = price_kaz * qty if price_kaz else 0

        # РРЦ в тенге: сырая РРЦ × курс
        raw_rrc   = float(bm.get("rrts") or 0)
        price_rrc = math.ceil(raw_rrc * cur_rate) if raw_rrc else 0
        sum_rrc   = price_rrc * qty if price_rrc else 0

        kp.cell(row=row, column=KP_BRAND,     value=brand)
        kp.cell(row=row, column=KP_ARTICLE,   value=article)
        kp.cell(row=row, column=KP_NAME,      value=name)
        kp.cell(row=row, column=KP_UNIT,      value=unit)
        kp.cell(row=row, column=KP_QTY,       value=qty)
        kp.cell(row=row, column=KP_PRICE_KP,  value=price_kp  or None)
        kp.cell(row=row, column=KP_SUM_KP,    value=sum_kp    or None)
        kp.cell(row=row, column=KP_COMMENT,   value=comment   or None)
        kp.cell(row=row, column=KP_DELIVERY,  value=delivery  or None)
        kp.cell(row=row, column=KP_PRICE_KAZ, value=price_kaz or None)
        kp.cell(row=row, column=KP_SUM_KAZ,   value=sum_kaz   or None)
        kp.cell(row=row, column=KP_KAZ_CODE,  value=kaz_code  or None)
        kp.cell(row=row, column=KP_PRICE_RRC, value=price_rrc or None)
        kp.cell(row=row, column=KP_SUM_RRC,   value=sum_rrc   or None)

        row += 1

    # Скрываем пустые строки после последней позиции (до конца таблицы)
    for r in range(row, KP_DATA_MAX + 1):
        kp.row_dimensions[r].hidden = True


def generate_excel(
    items: List[Dict],
    output_path: str,
    constants: Optional[Dict] = None,
    products: Optional[List[Dict]] = None,
    brand_consts: Optional[Dict] = None,
    project_name: str = "",
    client_name: str = "",
    manager_name: str = "",
) -> str:
    """
    Сохраняет результат в .xlsm на основе шаблона со всеми макросами.

    items         — список позиций с best_match, status, qty, _user_price, …
    constants     — ответ api.get_constants() (brands, managers, currencies)
    products      — ответ api.get_all_products() (все товары для листа БД)
    brand_consts  — {BRAND_UPPER: {margin, logistics, …}} (уже построен в preview_page)
    """
    out_path = output_path
    if not out_path.lower().endswith(".xlsm"):
        out_path = os.path.splitext(out_path)[0] + ".xlsm"

    tpl = _template_path()
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

    # 3. Заполняем лист WV 4.0 (только вводные колонки)
    _clear_input_rows(ws, start_row=2, end_row=max(465, 2 + len(items)))

    for i, item in enumerate(items):
        row = 2 + i
        bm      = item.get("best_match") or {}
        brand   = bm.get("brand") or ""
        article = bm.get("article") or item.get("article_raw") or ""
        qty     = item.get("qty", 1)

        ws.cell(row=row, column=WV_BRAND,   value=brand)
        ws.cell(row=row, column=WV_ARTICLE, value=article)
        ws.cell(row=row, column=WV_QTY,     value=qty)

        if item.get("_user_edited") and item.get("_user_price") is not None:
            try:
                ws.cell(row=row, column=WV_CONST_PRC, value=float(item["_user_price"]))
            except (TypeError, ValueError):
                pass
        elif item.get("_user_const_price") is not None:
            try:
                ws.cell(row=row, column=WV_CONST_PRC, value=float(item["_user_const_price"]))
            except (TypeError, ValueError):
                pass

        comment  = item.get("comment")  or ""
        delivery = item.get("delivery") or ""
        if comment:
            ws.cell(row=row, column=WV_COMMENT,  value=comment)
        if delivery:
            ws.cell(row=row, column=WV_DELIVERY, value=delivery)

    # 4. Заполняем шапку и данные листа КП
    _fill_kp_header(wb, manager_name, project_name, client_name)
    _fill_kp_data(wb, items, brand_consts or {})

    wb.save(out_path)
    return out_path
