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
    for r in range(KP_DATA_START, KP_DATA_START + 900):
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

    # ── 4. Очистить зону данных + старого подвала ───────────────────────────
    clear_end = итого_row + FOOTER_ROWS + 5
    for r in range(KP_DATA_START, clear_end):
        kp.row_dimensions[r].hidden = False
        for col in range(1, 20):
            cell = kp.cell(row=r, column=col)
            if cell.value is not None:
                cell.value = None

    # ── 4б. Определить фактическую границу шаблонной таблицы ───────────────
    actual_table_end = KP_DATA_MAX  # по умолчанию
    if kp_table:
        m_end = _re.search(r'[A-Za-z]+(\d+)$', kp_table.ref)
        if m_end:
            actual_table_end = int(m_end.group(1))

    # Строка-образец стиля (последняя строка в шаблонной таблице)
    style_src_row = actual_table_end

    # ── 5. Записать строки данных (колонки A–I, без КазНИИСА/РРЦ) ──────────
    last_data_row = KP_DATA_START - 1
    for i, item in enumerate(items):
        row  = KP_DATA_START + i
        bm   = item.get("best_match") or {}

        # Скопировать стиль для строк за пределами шаблонной таблицы
        if row > actual_table_end:
            for col in range(1, 10):
                src_cell = kp.cell(row=style_src_row, column=col)
                dst_cell = kp.cell(row=row, column=col)
                dst_cell.number_format = src_cell.number_format
                if src_cell.has_style:
                    try:
                        dst_cell.font      = _copy(src_cell.font)
                        dst_cell.border    = _copy(src_cell.border)
                        dst_cell.fill      = _copy(src_cell.fill)
                        dst_cell.alignment = _copy(src_cell.alignment)
                    except Exception:
                        pass

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

    # ── 8. Обновить ссылку Таблица5 (без insert_rows) ───────────────────────
    if kp_table and last_data_row >= KP_DATA_START:
        kp_table.ref = _re.sub(
            r'(\$?[A-Za-z]+\$?)\d+$',
            lambda m: m.group(1) + str(last_data_row),
            kp_table.ref,
        )


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

        # Если позиция не найдена в БД или нет артикула — формула VLOOKUP в столбце C
        # вернёт пустоту. Записываем наименование из PDF напрямую как fallback.
        db_name = bm.get("name", "")
        if not db_name:
            pdf_name = item.get("name_raw", "")
            if pdf_name:
                ws.cell(row=row, column=WV_NAME, value=pdf_name)

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
    return out_path
