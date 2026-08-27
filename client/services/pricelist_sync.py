"""
Сверка эксель-базы сегмента с прейскурантом КазНИИСА.

Прейскурант — источник актуальных сметных цен. Из ценовой ячейки берётся
верхнее число (сметная цена), умножается на НДС и записывается в колонку
«КазНИИСА» эксель-базы. Позиции прейскуранта, которым в базе не нашлось
пары, отдаются отдельным списком — их грузят в общую базу (сегмент gen).

Перед любой правкой рядом с исходным файлом создаётся датированная копия:
обратной операции у openpyxl нет, а цены — не тот материал, где уместно
полагаться на «отменить».

Сопоставление идёт по двум признакам, оба однозначные:
    1. код АГСК  — прямое совпадение;
    2. артикул   — если артикул целиком встречается в названии позиции
                   прейскуранта и такая позиция ровно одна; коротки́е
                   артикулы отсекаются, иначе «LC1» поймает полкаталога.

По словам наименования цены не подставляются. Совпадение формулировок
слишком часто означает похожий, но другой товар, а ошибка здесь тихая:
неверная цена попадёт в базу и всплывёт уже в коммерческом предложении.
Позиции, не опознанные по коду и артикулу, остаются со старой ценой.
"""
import os
import re
import shutil
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import openpyxl

# НДС, которым сметная цена приводится к цене в базе
VAT = 1.16

# Колонки листа «БД» (1-based, как в openpyxl)
COL_NUM, COL_ARTICLE, COL_NAME, COL_UNIT = 1, 2, 3, 4
COL_KAZNISA = 5          # цена КазНИИСА — единственная, которую правим
COL_BRAND, COL_MULT, COL_CODE = 10, 11, 12

# Артикул короче этого длиной для поиска по названию не годится
MIN_ARTICLE_LEN = 5

_SPACES = (" ", " ", " ", " ", " ")
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

# Слова, не несущие смысла при сравнении наименований
_STOP_WORDS = {
    "для", "или", "под", "над", "при", "без", "тип", "типа", "шт",
    "мм", "см", "м", "в", "с", "на", "из", "и", "по", "до",
}


# ─── Нормализация ────────────────────────────────────────────────────────────

def normalize_code(value) -> str:
    """Код АГСК без пробелов, переносов и хвостовых точек."""
    if value is None:
        return ""
    s = str(value)
    for sp in _SPACES:
        s = s.replace(sp, "")
    return s.replace("\n", "").strip()


# Разделители разрядов в выгрузках: обычный, неразрывный, узкий, апостроф
_GROUP_CHARS = " \u00a0\u202f\u2009\u2007\u2060'\u2019`"


def parse_number(val):
    """Цена из ячейки. Повторяет разбор импорта базы, чтобы одна и та же
    ячейка читалась одинаково и при загрузке в БД, и при сверке."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        return f if f > 0 else None

    s = str(val).strip()
    for ch in _GROUP_CHARS:
        s = s.replace(ch, "")
    if not s:
        return None

    dot, comma = s.rfind("."), s.rfind(",")
    if dot >= 0 and comma >= 0:
        dec = "." if dot > comma else ","
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    else:
        sep = "." if dot >= 0 else ("," if comma >= 0 else "")
        if sep:
            head, tail = s.rsplit(sep, 1)
            grouping = (s.count(sep) > 1
                        or (len(tail) == 3 and tail.isdigit()
                            and head.lstrip("-+") not in ("", "0")))
            s = s.replace(sep, "") if grouping else s.replace(sep, ".")

    try:
        f = float(s)
    except (ValueError, TypeError):
        return None
    return f if f > 0 else None


def _norm_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def _norm_unit(value) -> str:
    """Единица измерения без точки и регистра: «шт.» и «ШТ» — одно и то же."""
    return _norm_text(value).rstrip(".").lower()


def _tokens(text: str) -> set:
    """Значимые слова названия в нижнем регистре."""
    return {w.lower() for w in _TOKEN_RE.findall(text or "")
            if len(w) > 1 and w.lower() not in _STOP_WORDS}


# ─── Чтение эксель-базы ──────────────────────────────────────────────────────

def _find_db_sheet(wb) -> str:
    """Лист с базой: «БД», иначе первый лист с подходящей шапкой."""
    for nm in wb.sheetnames:
        if nm.strip().lower() in ("бд", "db", "база"):
            return nm
    for nm in wb.sheetnames:
        ws = wb[nm]
        head = [_norm_text(ws.cell(row=1, column=c).value).lower()
                for c in range(1, 13)]
        if any("артикул" in h for h in head) and any("наимен" in h for h in head):
            return nm
    return wb.sheetnames[0]


def read_base_rows(path: str) -> Tuple[List[dict], str]:
    """Читает эксель-базу. Возвращает (строки, имя листа).

    Значения берутся вычисленными (data_only), чтобы формулы не попали
    в сравнение как текст.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = _find_db_sheet(wb)
        ws = wb[sheet]
        rows = []
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(v is None for v in row):
                continue

            def cell(i):
                return row[i - 1] if len(row) >= i else None

            article = _norm_text(cell(COL_ARTICLE))
            name    = _norm_text(cell(COL_NAME))
            code    = normalize_code(cell(COL_CODE))
            if not (article or name or code):
                continue

            kaznisa = parse_number(cell(COL_KAZNISA))

            rows.append({
                "row":     idx,
                "article": article,
                "name":    name,
                "unit":    _norm_text(cell(COL_UNIT)) or "шт.",
                "brand":   _norm_text(cell(COL_BRAND)),
                "code":    code,
                "kaznisa": kaznisa,
            })
        return rows, sheet
    finally:
        wb.close()


# ─── Сопоставление ───────────────────────────────────────────────────────────

class _TokenIndex:
    """Обратный индекс слов прейскуранта.

    Без него сверка вырождается в перебор «каждая строка базы против каждой
    позиции прейскуранта» — на реальных объёмах (сотни тысяч строк против
    десятков тысяч кодов) это миллиарды сравнений. Индекс сужает круг
    кандидатов до позиций, у которых есть хотя бы одно общее слово.

    Слишком частые слова («кабель», «светильник») из поиска исключаются:
    они не сужают выбор, а только замедляют его.
    """

    # Слово, встречающееся чаще этой доли позиций, кандидатов не отбирает
    _MAX_DF = 0.10

    def __init__(self, entries: List[dict]):
        self.entries = entries
        self._tokens = [_tokens(e.get("name", "")) for e in entries]

        df: Dict[str, int] = {}
        for ts in self._tokens:
            for tok in ts:
                df[tok] = df.get(tok, 0) + 1

        limit = max(3, int(len(entries) * self._MAX_DF))
        self._postings: Dict[str, list] = {}
        for i, ts in enumerate(self._tokens):
            for tok in ts:
                if df[tok] <= limit:
                    self._postings.setdefault(tok, []).append(i)

    def _candidates(self, text: str) -> set:
        ids: set = set()
        for tok in _tokens(text):
            ids.update(self._postings.get(tok, ()))
        return ids

    def by_article(self, article: str) -> list:
        """Позиции, в названии которых артикул встречается целиком."""
        needle = article.lower()
        hits = []
        for i in self._candidates(article):
            if needle in (self.entries[i].get("name") or "").lower():
                hits.append(self.entries[i])
                if len(hits) > 1:      # неоднозначно — дальше можно не искать
                    break
        return hits


def match_base_to_pricelist(
    base_rows: List[dict],
    pricelist: Dict[str, dict],
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """Сопоставляет строки базы с позициями прейскуранта.

    Возвращает:
        matched  — строки с новой ценой, готовые к записи;
        unmatched_base      — строк базы не нашлось в прейскуранте;
        unmatched_pricelist — коды прейскуранта, не найденные в базе.
    """
    by_code = {normalize_code(c): dict(e, code=normalize_code(c))
               for c, e in pricelist.items()}

    entries = list(by_code.values())
    index = _TokenIndex(entries)
    used_codes: set = set()

    matched, unmatched_base = [], []
    total = len(base_rows) or 1

    for i, br in enumerate(base_rows):
        if progress_cb and i % 200 == 0:
            progress_cb(int(i / total * 100), f"Сверка позиций: {i:,} из {total:,}")

        entry, how = None, ""

        # 1. Код АГСК
        if br["code"] and br["code"] in by_code:
            entry, how = by_code[br["code"]], "код"

        # 2. Артикул целиком внутри названия прейскуранта
        if entry is None and len(br["article"]) >= MIN_ARTICLE_LEN:
            hits = index.by_article(br["article"])
            if len(hits) == 1:
                entry, how = hits[0], "артикул"

        if entry is None:
            unmatched_base.append(br)
            continue

        used_codes.add(entry["code"])
        old = br["kaznisa"]
        new = round(float(entry["price"]) * VAT, 2)
        matched.append({
            **br,
            "how":        how,
            "code_pl":    entry["code"],
            "name_pl":    entry.get("name", ""),
            "unit_pl":    entry.get("unit", ""),
            "price_pl":   float(entry["price"]),
            "price_new":  new,
            "price_old":  old,
            "diff_abs":   (new - old) if old else None,
            "diff_pct":   ((new - old) / old * 100.0) if old else None,
        })

    unmatched_pricelist = [e for c, e in by_code.items() if c not in used_codes]
    unmatched_pricelist.sort(key=lambda e: e["code"])

    if progress_cb:
        progress_cb(100, "Сверка завершена")

    changed = [m for m in matched if m["price_old"] is None
               or abs(m["price_new"] - m["price_old"]) > 0.005]
    return {
        "matched":             matched,
        "changed":             changed,
        "unmatched_base":      unmatched_base,
        "unmatched_pricelist": unmatched_pricelist,
        "stats": {
            "base_rows":        len(base_rows),
            "pricelist_codes":  len(by_code),
            "matched":          len(matched),
            "by_code":          sum(1 for m in matched if m["how"] == "код"),
            "by_article":       sum(1 for m in matched if m["how"] == "артикул"),
            "changed":          len(changed),
            "unmatched_base":   len(unmatched_base),
            "to_general":       len(unmatched_pricelist),
            "vat":              VAT,
        },
    }


# ─── Запись обратно в файл ───────────────────────────────────────────────────

def make_dated_backup(path: str) -> str:
    """Копия файла рядом с оригиналом, с датой в имени.

    «База ОС.xlsx» → «База ОС (до сверки 2026-08-25).xlsx».
    Если такая копия уже есть, добавляется время — за день сверку могут
    прогнать не один раз, и затирать утреннюю копию вечерней нельзя.
    """
    folder, fname = os.path.split(path)
    stem, ext = os.path.splitext(fname)
    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = os.path.join(folder, f"{stem} (до сверки {stamp}){ext}")
    if os.path.exists(dest):
        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        dest = os.path.join(folder, f"{stem} (до сверки {stamp}){ext}")
    shutil.copy2(path, dest)
    return dest


# Колонки, которые читает импорт базы в БД
_IMPORT_COLS = range(1, 13)


def write_prices_to_base(path: str, changed: List[dict],
                         sheet_name: str = "") -> dict:
    """Записывает новые цены КазНИИСА в исходный файл.

    Возвращает {"written": N, "formula_cells": M, "formula_cols": [...]}.

    Про formula_cells важно знать вот что: openpyxl сохраняет формулу, но
    не её посчитанное значение. Excel при открытии пересчитает, а
    приложение читает файл с data_only=True и увидит пустые ячейки. Если
    цены в базе заданы формулами, после записи файл обязательно нужно
    один раз открыть в Excel и сохранить — иначе следующий импорт
    обнулит эти позиции.

    Пишется только колонка E. Файл собирается во временный и подменяется
    одним движением: обрыв записи не оставит менеджера с половиной базы.
    """
    if not changed:
        return {"written": 0, "formula_cells": 0, "formula_cols": []}

    wb = openpyxl.load_workbook(path, data_only=False,
                                keep_vba=path.lower().endswith(".xlsm"))
    try:
        sheet = sheet_name if sheet_name in wb.sheetnames else _find_db_sheet(wb)
        ws = wb[sheet]

        written = 0
        for m in changed:
            cell = ws.cell(row=m["row"], column=COL_KAZNISA)
            cell.value = m["price_new"]
            cell.number_format = "#,##0.00"
            written += 1

        # Сколько значений потеряет импорт, пока файл не пересчитан Excel
        formula_cells = 0
        formula_cols: set = set()
        for row in ws.iter_rows(min_row=2, max_col=12):
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    formula_cells += 1
                    formula_cols.add(c.column)

        tmp = path + ".tmp"
        wb.save(tmp)
    finally:
        wb.close()

    os.replace(tmp, path)
    return {"written": written,
            "formula_cells": formula_cells,
            "formula_cols": sorted(formula_cols)}
