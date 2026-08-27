import customtkinter as ctk
import os
import subprocess
import sys
from tkinter import ttk, filedialog, messagebox
import tkinter as tk
import math
from typing import List, Dict, Optional

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService
from ui.dialogs.analog_dialog import AnalogDialog
from services.excel_generator import generate_excel


# Цвета строк
C_EXACT    = "#D4EDDA"
C_MULTIPLE = "#FFF3CD"
C_NOTFOUND = "#F8D7DA"
C_EDITED   = "#CCE5FF"
C_SELECT   = "#C8DFFF"
C_AI       = "#B0BEC5"   # серебристый — ИИ-совпадение (высокая уверенность)
C_AI_LOW   = "#F5F5F5"   # почти белый — ИИ-совпадение (низкая уверенность, требует проверки)
C_MANAGER  = "#EDE7F6"   # сиреневый — подобрано из истории выборов менеджеров
C_HEADING  = "#D6EAF8"   # голубой — строка-заголовок раздела (is_heading=True)
C_ANALOG      = "#B2EBF2"   # циановый — строка аналога (is_analog_row=True)
C_READY       = "#A9DFBF"   # насыщенный зелёный — есть и артикул, и код АГСК
C_EST_BELOW   = "#A9DFBF"   # наша цена ниже сметной — хорошо
C_EST_ABOVE   = "#F5B7B1"   # наша цена выше сметной — плохо
C_ANOMALY_FG  = "#B03A2E"   # текст строки с несопоставимыми ценами

# Во сколько раз цена может законно отличаться от себестоимости.
# Реальная наценка — 1.2–3×; всё выше означает разные единицы измерения
# либо ошибку импорта прайса, а не бизнес-решение.
ANOMALY_RATIO = 20.0
C_ORIG_ANALOG = "#ECEFF1"   # светло-серый — оригинал, замещённый аналогом


# Колонки строго в порядке WV 4.0 + два служебных
# Внутренний ключ → ярлык (берём из локализации)
COLS = [
    ("pos",        "col_num"),          # 0 — № позиции из PDF
    ("brand",      "col_brand"),        # 1
    ("article",    "col_art_db"),       # 2 — артикул из БД
    ("name",       "col_name_db"),      # 3 — наименование из БД
    ("unit",       "col_unit"),         # 4
    ("qty",        "col_qty"),          # 5  редактируется
    ("mult",       "col_mult"),         # 6 — кратность
    ("seb",        "col_price_seb"),    # 7 — Цена себес
    ("seb_sum",    "col_sum_seb"),      # 8 — Сумма себес
    ("const",      "col_const"),        # 9 — Предварительная цена, редактируется
    ("kp",         "col_price_kp"),     # 10 — Цена КП, редактируется
    ("kp_sum",     "col_sum_kp"),       # 11 — Сумма КП
    ("est_price",  "col_est_price"),    # 12 — Сметная цена, редактируется
    ("est_sum",    "col_est_sum"),      # 13 — Сметная сумма
    ("kaznisa",    "col_kaznisa_code"), # 14 — Код АГСК
    ("comment",    "col_comment"),      # 13 — Комментарии (редактируется)
    ("delivery",   "col_delivery"),     # 14 — Срок поставки (редактируется)
    ("status",     "col_status"),       # 15 — Статус
    ("method",     "col_method"),       # 16 — Метод подбора
    ("analog_art", "col_analog"),        # 17 — Аналог из базы аналогов
]
COL_WIDTHS    = [40, 90, 170, 230, 50, 60, 60, 90, 100, 150, 90, 100, 120, 120, 110, 150, 110, 100, 130, 120]
EDITABLE_COLS = {2, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16}  # Артикул, Кол-во, Кратн., цены, Сметная цена, Код АГСК, Коммент., Срок
C_ARTICLE   = 2                                  # индекс колонки «Артикул (БД)»
C_EST_PRICE = 12                                 # «Сметная цена» — можно вписать вручную
C_EST_SUM   = 13                                 # «Сметная сумма» — считается
C_KAZ_CODE  = 14                                 # индекс колонки «Код АГСК»
# Индексы колонок ценового блока
C_SEB, C_SEB_SUM, C_PRELIM, C_KP, C_KP_SUM = 7, 8, 9, 10, 11


# Соответствие rate-индекс (1..8) → ключ цены из БД
RATE_FIELD = {
    1: "kaznisa",  # Сумма АГСК  (kaznisa × кол-во)
    2: "kaznisa",  # Цена АГСК
    3: "rrts",     # РРЦ
    4: "mrc",      # МРЦ
    5: "opt",      # Опт
    6: "rrts",     # Цена ГП  (РРЦ × коэф. ГП)
    7: "rrts",     # Сумма ГП (РРЦ × коэф. ГП × кол-во)
    8: "partner",  # Проект
}
# Типы расценки, требующие умножения базовой цены на коэффициент ГП
GP_RATE_TYPES   = {6, 7}
# Типы расценки на основе цены КазНИИСА (АГСК): уже в тенге, коэффициенты курса/НДС/логистики НЕ применяются
AGSK_RATE_TYPES = {1, 2}

# Подписи типов расценки (индекс 1 = RATE_LABELS[0])
RATE_LABELS = [
    "Сумма АГСК",  # 1
    "Цена АГСК",   # 2
    "РРЦ",             # 3
    "МРЦ",             # 4
    "Опт",             # 5
    "Цена ГП",         # 6
    "Сумма ГП",        # 7
    "Проект",          # 8
]

# Расценки, доступные пользователю в выпадающем списке.
# «Цена АГСК» (2), «Цена ГП» (6) и «Сумма ГП» (7) скрыты — расчёт для них
# остаётся в коде, чтобы сохранённые в БД значения продолжали работать.
DEFAULT_RATE_IDX    = 1          # «Сумма АГСК» — расценка по умолчанию
VISIBLE_RATE_IDX    = [1, 3, 4, 5, 8]
VISIBLE_RATE_LABELS = [RATE_LABELS[i - 1] for i in VISIBLE_RATE_IDX]

# Коэффициент предварительной цены по умолчанию (переопределяется настройкой с сервера)
DEFAULT_PRELIM_COEFF = 1.9


def _norm_rate(value) -> int:
    """Приводит сохранённую расценку к используемой в интерфейсе.

    Значения вне видимого списка (в т.ч. старое МРЦ=4 из дефолта БД и
    скрытые «Цена АГСК»/«Цена ГП»/«Сумма ГП») заменяются на расценку
    по умолчанию — «Сумма АГСК».
    """
    try:
        idx = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_RATE_IDX
    return idx if idx in VISIBLE_RATE_IDX else DEFAULT_RATE_IDX


def _make_headers() -> List[str]:
    return [t(key) for _k, key in COLS]


# ── Лёгкий тултип для Treeview ────────────────────────────────────────────────

class _TreeTooltip:
    """Показывает тултип с AI-объяснением при наведении на строку Treeview."""

    DELAY_MS   = 500    # задержка перед появлением (мс)
    BG_COLOR   = "#2C3E50"
    FG_COLOR   = "#FFFFFF"
    FONT       = ("Calibri", 11)
    MAX_WIDTH  = 520    # символов

    def __init__(self, tree: ttk.Treeview, item_getter):
        """
        tree        — ttk.Treeview виджет
        item_getter — callable(iid) → item dict или None
        """
        self._tree        = tree
        self._get_item    = item_getter
        self._tip_window: Optional[tk.Toplevel] = None
        self._last_iid: Optional[str] = None
        self._after_id: Optional[str] = None

        tree.bind("<Motion>",   self._on_motion,  add="+")
        tree.bind("<Leave>",    self._hide,        add="+")
        tree.bind("<Button-1>", self._hide,        add="+")

    # ── handlers ──────────────────────────────────────────────────────────────

    def _on_motion(self, event):
        iid = self._tree.identify_row(event.y)
        if iid == self._last_iid:
            return
        self._hide()
        if not iid:
            return
        item = self._get_item(iid)
        if not item:
            return
        text = self._build_text(item)
        if not text:
            return
        self._last_iid = iid
        # Debounce: show after DELAY_MS without moving
        self._after_id = self._tree.after(
            self.DELAY_MS, lambda: self._show(event.x_root, event.y_root, text)
        )

    def _hide(self, event=None):
        if self._after_id:
            self._tree.after_cancel(self._after_id)
            self._after_id = None
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None
        self._last_iid = None

    def _show(self, x: int, y: int, text: str):
        if self._tip_window:
            return
        tip = tk.Toplevel(self._tree)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x + 14}+{y + 10}")
        tip.attributes("-topmost", True)

        lbl = tk.Label(
            tip, text=text, justify="left",
            background=self.BG_COLOR, foreground=self.FG_COLOR,
            font=self.FONT, relief="flat",
            padx=10, pady=6, wraplength=self.MAX_WIDTH,
        )
        lbl.pack()
        self._tip_window = tip

    # ── content builder ───────────────────────────────────────────────────────

    @staticmethod
    def _build_text(item: dict) -> str:
        parts = []

        ai_reason = (item.get("ai_reason") or "").strip()
        ai_conf   = item.get("ai_confidence")
        ai_used   = item.get("ai_used", False)
        ai_low    = item.get("ai_low_confidence", False)
        downgraded = item.get("ai_downgraded", False)

        if ai_used and ai_reason:
            conf_str = f"  ({ai_conf:.0%})" if ai_conf else ""
            prefix   = "⚠ " if (ai_low or downgraded) else "🤖 "
            parts.append(f"{prefix}{t('preview_info_ai')}: {ai_reason}{conf_str}")

        # Tech params
        tech = item.get("tech_params") or {}
        if tech:
            tp = "  |  ".join(f"{k}: {v}" for k, v in list(tech.items())[:7])
            parts.append(f"{t('preview_info_tech')}: {tp}")

        # Best match info
        bm = item.get("best_match") or {}
        if bm and bm.get("name"):
            parts.append(f"{t('preview_info_db')}: {bm.get('article','')} — {bm.get('name','')[:100]}")

        return "\n".join(parts)


class CandidateDialog(ctk.CTkToplevel):
    def __init__(self, parent, candidates: list):
        super().__init__(parent)
        self.candidates = candidates
        self.selected   = None
        self.title(t("cand_title"))
        self.geometry("700x420")
        self.grab_set()
        self.resizable(True, False)
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("cand_label"),
                     font=FONT_NORMAL, text_color=NAVY).pack(pady=(16, 8), padx=20, anchor="w")
        frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        cols = ["score", "article", "name", "brand", "rrts", "mrc"]
        hdrs = ["%", "Артикул", "Наименование", "Бренд", "РРЦ", "МРЦ"]
        style = ttk.Style()
        style.configure("Cand.Treeview", rowheight=28, font=("Calibri", 12))
        style.configure("Cand.Treeview.Heading", font=("Calibri", 14, "bold"),
                        background=NAVY, foreground="white")
        style.map("Cand.Treeview", background=[("selected", C_SELECT)])
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                  style="Cand.Treeview", selectmode="browse")
        for col, hdr, w in zip(cols, hdrs, [40, 180, 280, 90, 90, 90]):
            self.tree.heading(col, text=hdr)
            # Добавляем stretch=False, чтобы колонка не прыгала обратно
            # Добавляем minwidth, чтобы пользователь не мог скрыть её совсем
            self.tree.column(col, width=w, minwidth=w // 20, stretch=0, anchor="center" if col == "score" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for c in self.candidates:
            score = int(c.get("score", 0))
            tag   = "exact" if score >= 95 else "fuzzy"
            vals  = (f"{score}%", c.get("article",""), c.get("name",""),
                     c.get("brand",""), c.get("rrts",""), c.get("mrc",""))
            self.tree.insert("", "end", values=vals, tags=(tag,))
        self.tree.tag_configure("exact", background=C_EXACT)
        self.tree.tag_configure("fuzzy", background=C_MULTIPLE)
        self.tree.bind("<Double-1>", lambda e: self._ok())
        # Авто-выделение первой строки — чтобы Enter / кнопка «Выбрать» сразу работали
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(0, 16), padx=16, fill="x")
        ctk.CTkButton(btn_row, text=t("cand_cancel"),
                      fg_color="#AEB6BF", hover_color="#95A5A6",
                      width=120, command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text=t("cand_ok"),
                      fg_color=NAVY_LIGHT, hover_color=NAVY,
                      width=140, command=self._ok).pack(side="right")

    def _ok(self):
        sel = self.tree.selection()
        if not sel:
            # Если есть единственный кандидат — выбираем его автоматически
            children = self.tree.get_children()
            if len(children) == 1:
                sel = (children[0],)
            else:
                messagebox.showwarning(t("cand_title"),
                                        t("cand_no_selection"))
                return
        idx = self.tree.index(sel[0])
        self.selected = self.candidates[idx]
        self.destroy()


class SaveKPDialog(ctk.CTkToplevel):
    """Окно для ввода Менеджер / Проект / Клиент перед сохранением."""
    def __init__(self, parent, managers: List[str]):
        super().__init__(parent)
        self.title(t("save_kp_title"))
        self.geometry("520x360")
        self.grab_set()
        self.resizable(False, False)
        self.result = None  # dict | None
        self._build(managers)

    def _build(self, managers):
        pad = 20
        ctk.CTkLabel(self, text=t("save_kp_subtitle"),
                     font=FONT_HEADING, text_color=NAVY).pack(pady=(pad, 6))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(pady=10, padx=pad, fill="x")

        ctk.CTkLabel(form, text=t("save_kp_manager"), anchor="w",
                     font=FONT_NORMAL).pack(fill="x")
        self.manager_var = ctk.StringVar(value=managers[0] if managers else "")
        self.manager_dd = ctk.CTkOptionMenu(form, values=managers or [""],
                                            variable=self.manager_var,
                                            width=460, height=34)
        self.manager_dd.pack(fill="x", pady=(2, 12))

        ctk.CTkLabel(form, text=t("save_kp_project"), anchor="w",
                     font=FONT_NORMAL).pack(fill="x")
        self.project_entry = ctk.CTkEntry(form, height=34, font=FONT_NORMAL)
        self.project_entry.pack(fill="x", pady=(2, 12))

        ctk.CTkLabel(form, text=t("save_kp_client"), anchor="w",
                     font=FONT_NORMAL).pack(fill="x")
        self.client_entry = ctk.CTkEntry(form, height=34, font=FONT_NORMAL)
        self.client_entry.pack(fill="x", pady=(2, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(12, pad), padx=pad, fill="x")
        ctk.CTkButton(btn_row, text=t("save_kp_cancel"),
                      fg_color="#AEB6BF", hover_color="#95A5A6",
                      width=140, command=self._cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text=t("save_kp_ok"),
                      fg_color=NAVY_LIGHT, hover_color=NAVY,
                      width=160, command=self._ok).pack(side="right")

    def _ok(self):
        self.result = {
            "manager": self.manager_var.get().strip(),
            "project": self.project_entry.get().strip(),
            "client":  self.client_entry.get().strip(),
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class ArticleSearchDialog(ctk.CTkToplevel):
    """
    Диалог поиска товара в базе данных.
    Показывает данные из PDF (артикул, наименование, код АГСК), позволяет
    выбрать сегмент базы и выполнить единый поиск по всем полям сразу.
    """

    _SEG_LABELS = ["Слаботочные", "Освещение", "Силовые"]
    _SEG_CODES  = ["ss", "os", "sil"]

    def __init__(self, parent, api: ApiService, item: dict, default_segment: str = "ss"):
        super().__init__(parent)
        self.api      = api
        self.item     = item
        self.selected = None

        self.title(t("search_dialog_title"))
        self.geometry("900x620")
        self.grab_set()
        self.resizable(True, True)
        self.minsize(680, 460)

        # Данные из PDF
        self._pdf_art   = (item.get("article_raw")      or "").strip()
        self._pdf_name  = (item.get("name_raw")          or "").strip()
        self._pdf_code  = (item.get("kaznisa_code_raw")  or "").strip()

        # Начальный сегмент
        self._default_seg = default_segment if default_segment in self._SEG_CODES else "ss"

        self._build()
        # Авто-поиск: берём лучший из имеющихся запросов
        if self._pdf_art or self._pdf_name or self._pdf_code:
            self.after(150, self._do_search)

    def _build(self):
        pad = 16

        # ── Заголовок ─────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text=t("search_dialog_title"),
                     font=FONT_HEADING, text_color=NAVY).pack(pady=(pad, 2), padx=pad, anchor="w")

        # ── Блок «Полученные данные из PDF» ───────────────────────────────────
        pdf_frame = ctk.CTkFrame(self, fg_color="#EBF5FB", corner_radius=RADIUS_MD,
                                  border_width=1, border_color="#AED6F1")
        pdf_frame.pack(fill="x", padx=pad, pady=(4, 8))
        pdf_frame.grid_columnconfigure((1, 3, 5), weight=1)

        ctk.CTkLabel(pdf_frame, text="Данные из PDF:",
                     font=(*FONT_SMALL[:2], "bold"), text_color=NAVY).grid(
            row=0, column=0, padx=(12, 6), pady=8, sticky="w")

        for col_idx, (label, value) in enumerate([
            ("Артикул",    self._pdf_art  or "—"),
            ("Наименование", self._pdf_name[:70] + ("…" if len(self._pdf_name) > 70 else "") if self._pdf_name else "—"),
            ("Код АГСК", self._pdf_code or "—"),
        ]):
            lbl_col = col_idx * 2 + 1
            val_col = col_idx * 2 + 2
            ctk.CTkLabel(pdf_frame, text=f"{label}:", font=FONT_SMALL,
                         text_color=TEXT_SECONDARY).grid(
                row=0, column=lbl_col, padx=(4, 2), pady=8, sticky="e")
            ctk.CTkLabel(pdf_frame, text=value, font=FONT_SMALL,
                         text_color=NAVY, anchor="w").grid(
                row=0, column=val_col, padx=(0, 12), pady=8, sticky="w")

        # ── Выбор сегмента ────────────────────────────────────────────────────
        seg_frame = ctk.CTkFrame(self, fg_color="transparent")
        seg_frame.pack(fill="x", padx=pad, pady=(0, 6))
        seg_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(seg_frame, text="База данных:", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).grid(row=0, column=0, padx=(0, 10), sticky="w")

        try:
            default_idx = self._SEG_CODES.index(self._default_seg)
        except ValueError:
            default_idx = 0
        self._seg_var = tk.StringVar(value=self._SEG_LABELS[default_idx])
        self._seg_btn = ctk.CTkSegmentedButton(
            seg_frame,
            values=self._SEG_LABELS,
            variable=self._seg_var,
            font=FONT_NORMAL,
            selected_color=NAVY,
            selected_hover_color=NAVY_DARK,
            unselected_color="#5D6D7E",
            unselected_hover_color="#4A5568",
            text_color="white",
            dynamic_resizing=True,
            height=34,
            command=lambda _: self._do_search(),
        )
        self._seg_btn.grid(row=0, column=1, sticky="ew")

        # ── Единое поле поиска ────────────────────────────────────────────────
        search_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                                     border_width=1, border_color="#E0E0E0")
        search_frame.pack(fill="x", padx=pad, pady=(0, 6))
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(search_frame, text="🔍  Поиск:",
                     font=FONT_NORMAL, text_color=TEXT_SECONDARY).grid(
            row=0, column=0, padx=(12, 6), pady=10, sticky="e")

        # Предзаполняем: приоритет — артикул, потом код АГСК, потом имя
        default_q = self._pdf_art or self._pdf_code or self._pdf_name[:60]
        self._q_var = tk.StringVar(value=default_q)
        q_entry = ctk.CTkEntry(search_frame, textvariable=self._q_var,
                                placeholder_text="Артикул, наименование или код АГСК…",
                                height=34, font=FONT_NORMAL)
        q_entry.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="ew")
        q_entry.bind("<Return>", lambda e: self._do_search())

        ctk.CTkButton(
            search_frame, text="🔍  Найти", font=FONT_NORMAL,
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=34, width=130, corner_radius=RADIUS_SM,
            command=self._do_search,
        ).grid(row=0, column=2, padx=(0, 12), pady=10)

        # ── Статус ────────────────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
                                         text_color=TEXT_SECONDARY)
        self._status_lbl.pack(padx=pad, anchor="w", pady=(0, 4))

        # ── Таблица результатов ───────────────────────────────────────────────
        tree_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                                   border_width=1, border_color="#E0E0E0")
        tree_frame.pack(fill="both", expand=True, padx=pad, pady=(0, 8))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        cols = ["article", "name", "brand", "unit", "kaznisa_code", "rrts", "mrc"]
        hdrs = [t("search_col_article"), t("search_col_name"),
                t("search_col_brand"), "Ед.", "Код АГСК", "РРЦ", "МРЦ"]
        widths = [150, 280, 90, 40, 120, 80, 80]

        style = ttk.Style()
        style.configure("Search.Treeview", rowheight=23, font=("Calibri", 10))
        style.configure("Search.Treeview.Heading", font=("Calibri", 12, "bold"),
                        background=NAVY, foreground="white")
        style.map("Search.Treeview", background=[("selected", C_SELECT)])

        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                   style="Search.Treeview", selectmode="browse")
        for col, hdr, w in zip(cols, hdrs, widths):
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=w, minwidth=30,
                              stretch=(col == "name"), anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<Double-1>", lambda e: self._ok())

        self._results: list = []

        # ── Кнопки ────────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(0, pad), padx=pad, fill="x")

        ctk.CTkButton(btn_row, text=t("search_cancel_btn"),
                      fg_color="#AEB6BF", hover_color="#95A5A6",
                      width=130, command=self.destroy).pack(side="right", padx=(8, 0))
        self._ok_btn = ctk.CTkButton(btn_row, text=t("search_select_btn"),
                                      fg_color=NAVY_LIGHT, hover_color=NAVY,
                                      width=150, command=self._ok, state="disabled")
        self._ok_btn.pack(side="right")

        self.bind("<Return>", lambda e: self._ok() if self._results else None)

    def _current_segment(self) -> str:
        label = self._seg_var.get()
        try:
            return self._SEG_CODES[self._SEG_LABELS.index(label)]
        except (ValueError, IndexError):
            return "ss"

    def _do_search(self, _=None):
        q = self._q_var.get().strip()
        if not q:
            return

        self._status_lbl.configure(text=t("search_searching"), text_color=TEXT_SECONDARY)
        self._tree.delete(*self._tree.get_children())
        self._results = []
        self._ok_btn.configure(state="disabled")

        seg = self._current_segment()

        def _worker():
            try:
                db_results  = self.api.search_products(q=q, segment=seg)
                sem_results = []
                if len(db_results) < 5 and self._pdf_name:
                    sem_results = self.api.search_products_by_text(
                        self._pdf_name, self._pdf_art, top_k=5)
                self.after(0, lambda: self._show_results(db_results, sem_results))
            except Exception as exc:
                self.after(0, lambda: self._status_lbl.configure(
                    text=f"Ошибка поиска: {exc}", text_color="#E74C3C"
                ))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _show_results(self, db_results: list, sem_results: list):
        self._tree.delete(*self._tree.get_children())
        self._results = []
        seen_ids: set = set()

        def _fmt(v):
            try:
                return f"{float(v):,.0f}" if v else "—"
            except Exception:
                return "—"

        def _add(p, tag=""):
            pid = p.get("id") or p.get("product_id")
            if not pid or pid in seen_ids:
                return
            seen_ids.add(pid)
            self._results.append(p)
            self._tree.insert("", "end", tags=(tag,) if tag else (), values=(
                p.get("article", ""),
                (p.get("name") or "")[:120],
                p.get("brand", ""),
                p.get("unit", "шт."),
                p.get("kaznisa_code", "") or "—",
                _fmt(p.get("rrts")),
                _fmt(p.get("mrc")),
            ))

        for p in db_results:
            _add(p, "db")

        if sem_results:
            for s in sem_results:
                if s.get("product_id") and s.get("article"):
                    _add({"id": s["product_id"], "article": s["article"],
                          "name": s.get("name", ""), "brand": "",
                          "unit": "шт.", "kaznisa_code": ""}, "sem")

        self._tree.tag_configure("db",  background=C_EXACT)
        self._tree.tag_configure("sem", background=C_MANAGER)

        if self._results:
            children = self._tree.get_children()
            if children:
                self._tree.selection_set(children[0])
                self._tree.focus(children[0])
            self._ok_btn.configure(state="normal")
            hint = "  (+ семантические)" if sem_results else ""
            self._status_lbl.configure(
                text=f"Найдено: {len(self._results)} позиций{hint}",
                text_color=TEXT_SECONDARY,
            )
        else:
            self._ok_btn.configure(state="disabled")
            self._status_lbl.configure(text=t("search_no_results"), text_color="#E74C3C")

    def _ok(self):
        sel = self._tree.selection()
        if not sel:
            children = self._tree.get_children()
            if len(children) == 1:
                sel = (children[0],)
            else:
                return
        idx = self._tree.index(sel[0])
        if 0 <= idx < len(self._results):
            self.selected = self._results[idx]
        self.destroy()


class PreviewPage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api     = api
        self.app     = app
        self.items   = []
        self.constants   = {}       # raw из API
        self.brand_consts = {}      # {brand: {margin, logistics, rate, currency_rate, nds, gp}}
        self._prelim_coeff = DEFAULT_PRELIM_COEFF   # множитель Партнёр→предварительная цена
        self._estimate_path = ""    # путь прикреплённой сметы
        self._estimate_stats = {}   # статистика разбора и сопоставления
        self._spec_mode   = False   # True — работаем со спецификацией (режим подбора)
        self._spec_path   = ""      # путь исходного файла спецификации
        self._spec_sheet  = ""      # лист со спецификацией
        self.managers    = []
        self._edit_iid   = None
        self._edit_entry = None
        self._filter_mode = "all"
        self._suppress_recalc = False
        self._rate_str_var = None
        # Уникальный идентификатор сессии для группировки исправлений
        import uuid
        self._session_id    = str(uuid.uuid4())[:16]
        self._select_mode   = False
        self._hdg_var: "tk.BooleanVar | None" = None  # инициализируется в _build
        self._checked_items: set = set()   # id(item) выбранных строк
        self._deleted_items: list = []     # позиции удалённые через ппкм; возвращаются по «Сбросить»
        # Multi-project support
        self._projects: list = []
        self._current_project_idx: int = -1

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build(self):
        pad = PAD_MD

        # Топ-панель
        top = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                           border_width=1, border_color="#E0E0E0")
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 4))
        top.grid_columnconfigure(1, weight=1)

        self.title_lbl = ctk.CTkLabel(top, text=t("preview_title"),
                                       font=FONT_HEADING, text_color=NAVY, anchor="w")
        self.title_lbl.grid(row=0, column=0, padx=16, pady=12, sticky="w")
        self.stat_lbl = ctk.CTkLabel(top, text="", font=FONT_SMALL,
                                      text_color=NAVY_LIGHT)
        self.stat_lbl.grid(row=0, column=1, padx=8, sticky="w")

        filter_frame = ctk.CTkFrame(top, fg_color="transparent")
        filter_frame.grid(row=0, column=2, padx=8)
        self.filter_btns = {}
        for key, label_key in [("all","preview_filter_all"),
                                ("warn","preview_filter_warn"),
                                ("nf","preview_filter_nf")]:
            btn = ctk.CTkButton(filter_frame, text=t(label_key), font=FONT_SMALL,
                                height=30, width=130, corner_radius=RADIUS_SM,
                                fg_color=NAVY_LIGHT if key=="all" else "#AEB6BF",
                                hover_color=BLUE_MID,
                                command=lambda k=key: self._set_filter(k))
            btn.pack(side="left", padx=3)
            self.filter_btns[key] = btn

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        self.search_entry = ctk.CTkEntry(top, placeholder_text=t("preview_search_ph"),
                                          textvariable=self.search_var,
                                          width=200, height=32, font=FONT_NORMAL)
        self.search_entry.grid(row=0, column=3, padx=8)

        self.reset_btn = ctk.CTkButton(
            top, text=t("preview_reset"), font=FONT_SMALL,
            fg_color="#AEB6BF", hover_color="#7F8C8D", text_color="white",
            height=36, width=110, corner_radius=RADIUS_SM, command=self._reset_session
        )
        self.reset_btn.grid(row=0, column=4, padx=(8, 4))

        self.est_btn = ctk.CTkButton(
            top, text="📋 Сметные цены", font=FONT_SMALL,
            fg_color="#17A589", hover_color="#148F77", text_color="white",
            height=36, width=150, corner_radius=RADIUS_SM,
            command=self._apply_estimate_prices,
        )
        self.est_btn.grid(row=0, column=5, padx=(0, 4))

        self.save_btn = ctk.CTkButton(
            top, text=t("preview_save"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=36, width=180, corner_radius=RADIUS_SM,
            state="disabled", command=self._save
        )
        self.save_btn.grid(row=0, column=6, padx=(0, 4))


        # Легенда + кнопки выделения (одна строка)
        leg = ctk.CTkFrame(self, fg_color="transparent")
        leg.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, 4))

        # Кнопки справа — пакуем первыми (до пилюль), чтобы pack(side="right") работал правильно
        self.delete_checked_btn = ctk.CTkButton(
            leg, text="🗑 Удалить (0)",
            font=FONT_SMALL, fg_color="#E74C3C", hover_color="#C0392B",
            height=28, width=150, corner_radius=RADIUS_SM,
            command=self._delete_checked,
        )
        self.delete_checked_btn.pack(side="right", padx=(0, 0))
        self.delete_checked_btn.pack_forget()

        self.reset_checked_btn = ctk.CTkButton(
            leg, text="🔄 Сбросить (0)",
            font=FONT_SMALL, fg_color="#2E86AB", hover_color="#1A5E7A",
            height=28, width=150, corner_radius=RADIUS_SM,
            command=self._reset_checked,
        )
        self.reset_checked_btn.pack(side="right", padx=(0, 4))
        self.reset_checked_btn.pack_forget()

        self.select_btn = ctk.CTkButton(
            leg, text="☑ Выбрать",
            font=FONT_SMALL, fg_color="#AEB6BF", hover_color=NAVY_LIGHT,
            height=28, width=120, corner_radius=RADIUS_SM,
            command=self._toggle_select_mode,
        )
        self.select_btn.pack(side="right", padx=(8, 4))

        self._hdg_var = tk.BooleanVar(value=True)
        self.hdg_chk = ctk.CTkCheckBox(
            leg, text="Заголовки в Excel", font=FONT_SMALL,
            variable=self._hdg_var, onvalue=True, offvalue=False,
            width=130, checkbox_width=16, checkbox_height=16,
        )
        self.hdg_chk.pack(side="right", padx=(4, 8))

        for bg, key in [
            (C_EXACT,    "preview_legend_exact"),
            (C_MULTIPLE, "preview_legend_warn"),
            (C_NOTFOUND, "preview_legend_nf"),
            (C_EDITED,   "preview_legend_edit"),
            (C_AI,       "preview_legend_ai"),
            (C_MANAGER,  "preview_legend_manager"),
            (C_ANALOG,   "preview_legend_analog"),
        ]:
            lf = tk.Frame(leg, bg=bg, relief="solid", bd=1)
            lf.pack(side="left", padx=(0, 8))
            tk.Label(lf, text=f"  {t(key)}  ", bg=bg, font=("Calibri", 11)).pack()

        # Таблица
        tree_frame = ctk.CTkFrame(self, fg_color=BG_CARD,
                                   corner_radius=RADIUS_MD,
                                   border_width=1, border_color="#E0E0E0")
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=pad, pady=(0, 4))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("APS.Treeview",
                        background=BG_CARD, fieldbackground=BG_CARD,
                        rowheight=23, font=("Calibri", 10))
        style.configure("APS.Treeview.Heading",
                        background=NAVY, foreground="white",
                        font=("Calibri", 12, "bold"), relief="flat")
        style.map("APS.Treeview",
                  background=[("selected", C_SELECT)],
                  foreground=[("selected", "#000000")])

        cols = [f"c{i}" for i in range(len(COLS))]
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                  show="headings", style="APS.Treeview",
                                  selectmode="browse")
        hdrs = _make_headers()
        # minwidth — чтобы пользователь не мог скрыть колонку, сделав её уже
        # ширины подписи. Берём примерную ширину текста заголовка + 18 пикс.
        for i, (col, w, hdr) in enumerate(zip(cols, COL_WIDTHS, hdrs)):
            self.tree.heading(col, text=hdr)
            anchor = "center" if i in (0, 4, 5, 6) else "w"
            min_w = max(50, len(hdr) * 9 + 18)
            self.tree.column(col, width=max(w, min_w), minwidth=min_w,
                             anchor=anchor, stretch=False)

        # Скрываем колонки, которые не нужны на экране предпросмотра
        # (данные хранятся в vals и попадают в Excel — просто не отображаются)
        _HIDDEN_COLS = {13, 14}  # comment, delivery  (kaznisa_code=12 показываем — нужен для сил. систем)
        self.tree["displaycolumns"] = [
            f"c{i}" for i in range(len(COLS)) if i not in _HIDDEN_COLS
        ]

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("exact",    background=C_EXACT)
        self.tree.tag_configure("multiple", background=C_MULTIPLE)
        self.tree.tag_configure("notfound", background=C_NOTFOUND)
        self.tree.tag_configure("edited",   background=C_EDITED)
        self.tree.tag_configure("ai",       background=C_AI)
        self.tree.tag_configure("ai_low",   background=C_AI_LOW)
        self.tree.tag_configure("manager",  background=C_MANAGER)
        self.tree.tag_configure("heading",  background=C_HEADING,
                                font=("Calibri", 10, "bold"))
        self.tree.tag_configure("analog",       background=C_ANALOG)
        self.tree.tag_configure("ready",        background=C_READY)
        self.tree.tag_configure("est_below",    background=C_EST_BELOW)
        self.tree.tag_configure("est_above",    background=C_EST_ABOVE)
        # Только цвет текста: фон остаётся от основного тега строки
        self.tree.tag_configure("anomaly",      foreground=C_ANOMALY_FG)
        self.tree.tag_configure("orig_analog",  background=C_ORIG_ANALOG,
                                font=("Calibri", 10, "italic"))

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._on_tree_single_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Тултип с AI-объяснением при наведении
        def _item_by_iid(iid):
            return next((i for i in self.items if i.get("_iid") == iid), None)
        self._tooltip = _TreeTooltip(self.tree, _item_by_iid)

        # Контекстное меню (правая кнопка мыши)
        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(
            label=t("ctx_copy_article"),
            command=lambda: self._copy_cell("article"),
        )
        self._ctx_menu.add_command(
            label=t("ctx_copy_kaznisa"),
            command=lambda: self._copy_cell("kaznisa"),
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label=t("ctx_copy_row"),
            command=self._copy_row,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label=t("preview_btn_confirm_tip"),
            command=self._confirm_selected_row,
        )
        self._ctx_menu.add_command(
            label=t("preview_btn_search_tip"),
            command=self._search_and_replace_selected,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label=t("ctx_reset_item"),
            command=self._reset_item_selected,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label="🔍 Подобрать аналог",
            command=self._find_analog_selected,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label=t("ctx_delete_item"),
            command=self._delete_selected,
        )
        self.tree.bind("<Button-3>", self._show_ctx_menu)
        self.tree.bind("<Delete>",   lambda e: self._delete_selected())

        # ── Итог сравнения со сметой (появляется вместе со сметными ценами) ──
        self.est_bar = ctk.CTkFrame(self, fg_color="#FDF6E3",
                                    corner_radius=RADIUS_MD,
                                    border_width=2, border_color="#7D6608")
        self.est_bar.grid(row=3, column=0, sticky="ew", padx=pad, pady=(0, 6))
        self.est_bar.grid_columnconfigure(1, weight=1)
        self.est_bar.grid_remove()

        self.est_verdict_lbl = ctk.CTkLabel(
            self.est_bar, text="", font=(*FONT_HEADING[:2], "bold"),
            text_color=NAVY, width=210, anchor="w",
        )
        self.est_verdict_lbl.grid(row=0, column=0, rowspan=2,
                                  padx=(16, 12), pady=10, sticky="w")

        self.est_main_lbl = ctk.CTkLabel(
            self.est_bar, text="", font=(*FONT_NORMAL[:2], "bold"),
            text_color=NAVY, anchor="w", justify="left",
        )
        self.est_main_lbl.grid(row=0, column=1, sticky="w", pady=(10, 0))

        self.est_detail_lbl = ctk.CTkLabel(
            self.est_bar, text="", font=FONT_SMALL,
            text_color=TEXT_SECONDARY, anchor="w", justify="left",
        )
        self.est_detail_lbl.grid(row=1, column=1, sticky="w", pady=(2, 10))

        # Панель «Константы по бренду»
        cf = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                          border_width=1, border_color="#E0E0E0")
        cf.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, pad))

        self.const_title = ctk.CTkLabel(cf, text=t("preview_constants_brand"),
                                         font=(*FONT_NORMAL[:2], "bold"),
                                         text_color=NAVY)
        self.const_title.grid(row=0, column=0, padx=16, pady=(10, 6), sticky="w", columnspan=12)

        # Селектор бренда
        ctk.CTkLabel(cf, text=t("preview_brand_select"), font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).grid(row=1, column=0, padx=(16, 4), pady=(0, 10), sticky="w")
        self.brand_var = ctk.StringVar(value="—")
        self.brand_dd = ctk.CTkOptionMenu(cf, values=["—"], variable=self.brand_var,
                                           width=180, height=30,
                                           command=self._on_brand_select)
        self.brand_dd.grid(row=1, column=1, padx=(0, 16), pady=(0, 10))

        # Поля констант
        self.const_vars = {}
        const_items = [
            ("preview_margin",     "margin",        1.20),
            ("preview_logistics",  "logistics",     1.03),
            ("preview_nds",        "nds",           1.16),
            ("preview_currency",   "currency_rate", 1.00),
            ("preview_rate_type",  "rate",          DEFAULT_RATE_IDX),  # «Сумма АГСК»
        ]
        for col_i, (key, var_key, default) in enumerate(const_items):
            lbl = ctk.CTkLabel(cf, text=t(key), font=FONT_SMALL,
                                text_color=TEXT_SECONDARY)
            lbl.grid(row=1, column=2 + col_i * 2, padx=(8, 4), pady=(0, 10), sticky="w")
            if var_key == "rate":
                # Выпадающий список вместо числового поля
                _def_lbl = RATE_LABELS[int(default) - 1]
                if _def_lbl not in VISIBLE_RATE_LABELS:
                    _def_lbl = VISIBLE_RATE_LABELS[0]
                self._rate_str_var = ctk.StringVar(value=_def_lbl)
                rate_dd = ctk.CTkOptionMenu(
                    cf, values=VISIBLE_RATE_LABELS,
                    variable=self._rate_str_var,
                    width=170, height=30,
                    command=self._on_rate_select,
                )
                rate_dd.grid(row=1, column=3 + col_i * 2, padx=(0, 8), pady=(0, 10))
                # Храним индекс (int) в const_vars для совместимости с остальным кодом
                var = tk.DoubleVar(value=default)
                # НЕ трейсим — обновление идёт через _on_rate_select
                self.const_vars[var_key] = var
            else:
                var = tk.DoubleVar(value=default)
                var.trace_add("write", self._on_const_change)
                entry = ctk.CTkEntry(cf, textvariable=var, width=70, height=30, font=FONT_SMALL)
                entry.grid(row=1, column=3 + col_i * 2, padx=(0, 8), pady=(0, 10))
                self.const_vars[var_key] = var

        # ── Кнопки режима подбора по спецификации ───────────────────────────
        # Живут в панели констант: в верхней панели они не помещались.
        # Колонка-распорка прижимает их к правому краю.
        cf.grid_columnconfigure(12, weight=1)

        self.spec_save_btn = ctk.CTkButton(
            cf, text="💾 Сохранить в спецификацию",
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color="#1E8449", hover_color="#186A3B",
            height=32, width=230, corner_radius=RADIUS_SM,
            anchor="center",
            command=self._save_to_spec,
        )
        self.spec_kp_btn = ctk.CTkButton(
            cf, text="→ Перейти к КП",
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=230, corner_radius=RADIUS_SM,
            anchor="center",
            command=self._spec_to_kp,
        )

        self.attach_est_btn = ctk.CTkButton(
            cf, text="📎 Прикрепить сметный лист",
            font=FONT_SMALL,
            fg_color="#7D6608", hover_color="#5B4A06",
            height=32, width=230, corner_radius=RADIUS_SM,
            command=self._attach_estimate,
        )
        self.attach_est_btn.grid(row=3, column=13, padx=(8, 16),
                                 pady=(0, 10), sticky="e")

        # Подсказка
        self.hint_lbl = ctk.CTkLabel(cf, text=t("preview_rate_hint"),
                                      font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.hint_lbl.grid(row=2, column=0, columnspan=12, padx=16, pady=(0, 10), sticky="w")

        self._no_data_lbl = ctk.CTkLabel(self, text=t("preview_no_data"),
                                          font=FONT_HEADING, text_color="#AEB6BF")
        self._no_data_lbl.grid(row=2, column=0)
        self._no_data_lbl.lower()

    # ── Сброс сессии ─────────────────────────────────────────────────────────
    def _reset_session(self):
        """Сброс страницы к начальному состоянию — возврат на вкладку загрузки."""
        self._projects = []
        self._current_project_idx = -1
        self.items = []
        self.tree.delete(*self.tree.get_children())
        self._filter_mode = "all"
        self.search_var.set("")
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == "all" else "#AEB6BF")
        self.save_btn.configure(state="disabled")
        self.stat_lbl.configure(text="")
        self._no_data_lbl.lift()
        # Сметный лист тоже сбрасываем — он относился к прошлому проекту
        self._estimate_path  = ""
        self._estimate_stats = {}
        if hasattr(self, "est_bar"):
            self.est_bar.grid_remove()

        if hasattr(self.app, "hide_project_tabs"):
            self.app.hide_project_tabs()

        # Возвращаемся на загрузку с чистым списком файлов
        try:
            self.app.upload_page.reset()
        except Exception as e:
            print(f"[Сброс] upload_page.reset: {e}")

        self.app._switch_tab(0)

    # ── Данные ───────────────────────────────────────────────────────────────
    def load_multi_data(self, results: list):
        """Store each PDF result as a separate project; show tabs; load first."""
        self._projects = []
        for result in results:
            if not result:
                continue
            items = list(result.get("items", []))
            # Per-project sequential numbering (not cross-project)
            pos_counter = 0
            for it in items:
                if it.get("status") != "heading":
                    pos_counter += 1
                    it["pos"] = str(pos_counter)
            # Keep result["items"] pointing at the same list so load_data works
            result["items"] = items
            self._projects.append({
                "name":   result.get("filename", "PDF"),
                "result": result,
                "items":  items,
            })

        # Notify nav panel to show project tabs
        if hasattr(self.app, "show_project_tabs"):
            self.app.show_project_tabs([p["name"] for p in self._projects])

        if not self._projects:
            return

        self._current_project_idx = 0
        # load_data fetches constants from server (only once per multi-load)
        self.load_data(self._projects[0]["result"])

    def switch_project(self, idx: int):
        """Switch to a project tab without re-fetching constants from server."""
        if idx < 0 or idx >= len(self._projects):
            return
        self._current_project_idx = idx
        proj = self._projects[idx]

        # Reset UI state
        self._filter_mode = "all"
        self.search_var.set("")
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == "all" else "#AEB6BF")

        # Exit select mode if active
        if self._select_mode:
            self._select_mode = False
            self._checked_items.clear()
            self.select_btn.configure(fg_color="#AEB6BF", text="☑ Выбрать")
            self.tree.heading("c0", text=t("col_num"))
            self.delete_checked_btn.pack_forget()
            self.reset_checked_btn.pack_forget()

        # Set items for this project
        self.items = proj["items"]

        # Reset tree IDs (tree rebuilt by _populate)
        for it in self.items:
            it["_iid"] = None
            it.setdefault("_user_edited", False)
            it.setdefault("_user_price", None)
            it.setdefault("_user_const_price", None)
            it.setdefault("_user_seb_price", None)

        # Update brand dropdown from this project's items
        brands_in_data = sorted({
            ((it.get("best_match") or {}).get("brand") or "").strip()
            for it in self.items
            if (it.get("best_match") or {}).get("brand")
        })
        self._suppress_recalc = True
        if brands_in_data:
            self.brand_dd.configure(values=brands_in_data)
            self.brand_var.set(brands_in_data[0])
            self._load_const_fields(brands_in_data[0])
        else:
            self.brand_dd.configure(values=["—"])
            self.brand_var.set("—")
        self._suppress_recalc = False

        self._populate()
        self._update_stats()
        self.save_btn.configure(state="normal")
        self._no_data_lbl.lower()

        self.after(200, self._refresh_analog_col)

        # Sync active tab style in nav
        if hasattr(self.app, "_switch_project_tab_style"):
            self.app._switch_project_tab_style(idx)

    def save_all_excel(self):
        """Save all loaded projects to one multi-sheet Excel file."""
        if not self._projects:
            messagebox.showinfo("", "Нет проектов для сохранения.")
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить Excel всех проектов",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return

        try:
            # Compute KP prices for ALL projects before saving
            for proj in self._projects:
                for it in proj["items"]:
                    seb, seb_sum, kp, kp_sum = self._compute_kp(it)
                    it["_computed_kp_price"] = kp
                    it["_computed_kp_sum"]   = kp_sum
                    it["_computed_seb_price"] = seb
                    it["_computed_seb_sum"]   = seb_sum
                    it["_prelim_price"]       = self._prelim_price(it) or None

            _incl_hdg = self._hdg_var.get() if self._hdg_var else True
            gen_projects = [
                {
                    "name": p["name"],
                    "items": [
                        it for it in p["items"]
                        if _incl_hdg or not it.get("is_heading")
                    ],
                    "brand_consts": dict(self.brand_consts),
                }
                for p in self._projects
            ]

            from services.excel_generator import generate_excel_multi
            out = generate_excel_multi(
                projects=gen_projects,
                output_path=path,
                constants=self.constants,
            )

            total_pos = sum(
                sum(1 for it in p["items"]
                    if it.get("status") not in ("heading", "not_found"))
                for p in self._projects
            )
            if messagebox.askyesno(
                "Сохранить Excel всех проектов",
                f"Сохранено {len(self._projects)} файлов, {total_pos} позиций.\n"
                f"Файл: {out}\n\nОткрыть?",
            ):
                self._open_file(out)
        except Exception as e:
            import traceback; traceback.print_exc()
            messagebox.showerror("Ошибка сохранения", str(e))

    def load_spec_data(self, result: dict):
        """Загружает результат разбора спецификации и включает режим подбора."""
        self._spec_mode  = True
        self._spec_path  = result.get("source_path", "") or ""
        items = result.get("items", []) or []
        self._spec_sheet = next((i.get("sheet") for i in items if i.get("sheet")), "")

        self.load_data(result)

        self._spec_mode = True          # load_data сбрасывает флаг — возвращаем
        self._update_spec_mode_ui()

    def _update_spec_mode_ui(self):
        """Показывает кнопки подбора и прячет обычное сохранение (и наоборот)."""
        try:
            if self._spec_mode:
                self.save_btn.grid_remove()
                self.spec_save_btn.grid(row=1, column=13, padx=(8, 16),
                                        pady=(0, 4), sticky="e")
                self.spec_kp_btn.grid(row=2, column=13, padx=(8, 16),
                                      pady=(0, 10), sticky="e")
                self.spec_save_btn.configure(state="normal")
                self.spec_kp_btn.configure(state="normal")
            else:
                self.spec_save_btn.grid_remove()
                self.spec_kp_btn.grid_remove()
                self.save_btn.grid(row=0, column=6, padx=(0, 4))
        except Exception:
            pass

    def _spec_to_kp(self):
        """Переход от подбора к составлению КП с тем же списком позиций."""
        if not self.items:
            return
        n_found = sum(1 for i in self.items
                      if not i.get("is_heading") and i.get("best_match"))
        n_all = sum(1 for i in self.items if not i.get("is_heading"))
        if n_found < n_all:
            if not messagebox.askyesno(
                "Перейти к КП",
                f"Подобрано {n_found} из {n_all} позиций.\n"
                f"Неподобранные не попадут в КП.\n\nПродолжить?",
            ):
                return

        self._spec_mode = False
        self._update_spec_mode_ui()
        self.save_btn.configure(state="normal")
        # Перерисовываем: цвета строк теперь отражают результат поиска по базе,
        # а не готовность к выгрузке в спецификацию
        self._populate()
        self._update_stats()
        messagebox.showinfo(
            "Режим КП",
            "Список перенесён в режим составления КП.\n"
            "Цены и расценки доступны, сохранение — кнопкой «Сохранить».",
        )

    def _save_to_spec(self):
        """Записывает подбор обратно в исходный файл спецификации."""
        if not self._spec_path or not os.path.isfile(self._spec_path):
            path = filedialog.asksaveasfilename(
                title="Сохранить спецификацию",
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not path:
                return
            self._spec_path = path

        rows = [i for i in self.items
                if i.get("row") and not i.get("is_heading") and i.get("best_match")]
        if not rows:
            messagebox.showinfo("", "Нет подобранных позиций для записи.")
            return

        self.spec_save_btn.configure(state="disabled", text="Сохранение...")

        import threading

        def _work():
            try:
                from services.spec_writer import write_selection_to_spec
                n = write_selection_to_spec(
                    self._spec_path, self.items, sheet_name=self._spec_sheet,
                )
            except Exception as e:
                import traceback; traceback.print_exc()
                self.after(0, lambda: (
                    messagebox.showerror("Ошибка сохранения", str(e)),
                    self.spec_save_btn.configure(
                        state="normal", text="💾 Сохранить в спецификацию"),
                ))
                return

            # Подбор уходит в базу аналогов — для проектировщиков
            saved = 0
            for it in rows:
                bm  = it.get("best_match") or {}
                art = (it.get("article_raw") or "").strip()
                an  = (bm.get("article") or "").strip()
                if not art or not an or art == an:
                    continue
                try:
                    self.api.save_analog_db(
                        article=art,
                        analog_article=an,
                        segment=(bm.get("segment") or "ss"),
                        analog_name=bm.get("name"),
                        analog_brand=bm.get("brand"),
                        source="spec",
                    )
                    saved += 1
                except Exception:
                    pass

            self.after(0, lambda: (
                self.spec_save_btn.configure(
                    state="normal", text="💾 Сохранить в спецификацию"),
                messagebox.showinfo(
                    "Спецификация сохранена",
                    f"Записано позиций: {n}\n"
                    f"Сохранено в базу подбора: {saved}\n\n"
                    f"Файл: {self._spec_path}",
                ),
            ))

        threading.Thread(target=_work, daemon=True).start()

    def load_data(self, result: dict):
        # Сбрасываем фильтр и поиск чтобы не было «призраков» из предыдущего файла
        self._filter_mode = "all"
        self.search_var.set("")
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == "all" else "#AEB6BF")

        self._spec_mode = False
        self._update_spec_mode_ui()
        self.items = result.get("items", [])
        # Фиксируем базовые значения и сбрасываем флаги
        for it in self.items:
            bm = it.get("best_match") or {}
            it["_iid"] = None
            it["_user_edited"]      = False
            it["_user_price"]       = None
            it["_user_const_price"] = None
            it["_user_seb_price"]   = None

        # Подтягиваем константы с сервера
        self._suppress_recalc = True
        try:
            self.constants = self.api.get_constants()
            self.brand_consts = {}
            for b in self.constants.get("brands", []):
                self.brand_consts[(b.get("brand") or "").upper()] = {
                    "margin":        float(b.get("margin")        or 1.0),
                    "logistics":     float(b.get("logistics")     or 1.0),
                    # Расценка глобальная и всегда стартует с «Сумма АГСК»:
                    # сохранённое в БД значение — это legacy-умолчание модели
                    "rate":          DEFAULT_RATE_IDX,
                    "currency_rate": float(b.get("currency_rate") or 1.0),
                    "nds":           float(b.get("nds")           or 1.0),
                    "gp":            float(b.get("gp")            or 1.0),
                }
            # Менеджеры из Const (B-колонка) — приходят отдельно если сервер вернёт
            self.managers = self.constants.get("managers", [])
        except Exception as e:
            print(f"[Preview] get_constants: {e}")

        # Коэффициент предварительной цены (глобальная настройка администратора)
        try:
            _st = self.api.get_app_settings() or {}
            _c  = float(_st.get("prelim_price_coeff") or DEFAULT_PRELIM_COEFF)
            self._prelim_coeff = _c if _c > 0 else DEFAULT_PRELIM_COEFF
        except Exception as e:
            print(f"[Preview] get_app_settings: {e}")
            self._prelim_coeff = DEFAULT_PRELIM_COEFF

        # Заполняем dropdown брендов из присутствующих в результатах
        brands_in_data = sorted({
            ((it.get("best_match") or {}).get("brand") or "").strip()
            for it in self.items
            if (it.get("best_match") or {}).get("brand")
        })
        if brands_in_data:
            self.brand_dd.configure(values=brands_in_data)
            self.brand_var.set(brands_in_data[0])
            self._load_const_fields(brands_in_data[0])
        else:
            self.brand_dd.configure(values=["—"])
            self.brand_var.set("—")

        self._suppress_recalc = False

        self._populate()
        self._update_stats()
        self.save_btn.configure(state="normal")
        self._no_data_lbl.lower()

        # Смета, прикреплённая на странице загрузки, применяется сама
        _est = (result or {}).get("estimate_path") or ""
        if _est and os.path.isfile(_est):
            self.after(400, lambda p=_est: self._attach_estimate(p))
        self.after(200, self._refresh_analog_col)

        # Diagnostic: check if matched products have price data in DB
        self._check_prices_in_db()

    def _check_prices_in_db(self):
        """Diagnostic: fetch prices for matched products and print a summary to console."""
        try:
            articles = [
                (it.get("best_match") or {}).get("article", "")
                for it in self.items
                if it.get("best_match") and it.get("status") != "not_found"
            ]
            articles = [a for a in articles if a]
            if not articles:
                return
            prices = self.api.get_product_prices(articles[:50])  # limit to 50 for speed
            no_price = [p for p in prices if not any(p.get(f) for f in ("kaznisa","rrts","mrc","opt","partner"))]
            with_price = [p for p in prices if any(p.get(f) for f in ("kaznisa","rrts","mrc","opt","partner"))]
            print(f"[Prices] Checked {len(prices)} matched products: "
                  f"{len(with_price)} have prices, {len(no_price)} have NO prices in DB.")
            for p in no_price[:5]:
                print(f"  NO PRICE: {p.get('article')} / {p.get('name')} (brand={p.get('brand')})")
        except Exception as e:
            print(f"[Prices] Diagnostic check failed: {e}")

    def _load_const_fields(self, brand: str):
        """Загружает значения констант выбранного бренда в поля ввода."""
        consts = self.brand_consts.get(brand.upper())
        if not consts:
            return
        self._suppress_recalc = True
        for k in ("margin", "logistics", "nds", "currency_rate", "rate"):
            if k in self.const_vars and k in consts:
                if k == "rate":
                    rate_idx = _norm_rate(consts[k])
                    self.const_vars[k].set(rate_idx)
                    # Синхронизируем надпись в выпадающем списке
                    if self._rate_str_var and 1 <= rate_idx <= len(RATE_LABELS):
                        _lbl = RATE_LABELS[rate_idx - 1]
                        # Скрытая расценка (Цена АГСК / Цена ГП / Сумма ГП) —
                        # показываем ближайшую видимую, расчёт не меняем
                        if _lbl not in VISIBLE_RATE_LABELS:
                            _lbl = RATE_LABELS[(1 if rate_idx == 2 else 3) - 1]
                        self._rate_str_var.set(_lbl)
                else:
                    self.const_vars[k].set(consts[k])
        self._suppress_recalc = False

    def _on_brand_select(self, brand: str):
        self._load_const_fields(brand)
        # Пересчитываем цены для позиций этого бренда с загруженными константами
        self._recalc_for_brand(brand.strip().upper())

    def _on_rate_select(self, label: str):
        """Пользователь выбрал тип расценки — применяем глобально ко всем брендам."""
        try:
            idx = RATE_LABELS.index(label) + 1  # 1-based
        except ValueError:
            idx = 3
        self.const_vars["rate"].set(idx)
        # Обновляем rate во всех brand_consts (расценка — глобальная настройка)
        for bc in self.brand_consts.values():
            bc["rate"] = idx
        # Также обновляем текущий выбранный бренд (если brand_consts пустой — fallback)
        brand = self.brand_var.get().strip().upper()
        if brand and brand != "—":
            self.brand_consts.setdefault(brand, {})["rate"] = idx
        # Пересчитываем ВСЕ позиции
        self._recalc_all()

    def _is_ready_row(self, item: dict) -> bool:
        """True — позиция готова к выгрузке в спецификацию.

        Готовность = заполнены и артикул, и код АГСК; источник значения
        не важен (подобрано из базы или вписано вручную).

        Работает ТОЛЬКО в режиме подбора. При составлении КП цвет строки
        отражает результат поиска по базе: ненайденная позиция остаётся
        красной, даже если артикул и код проставлены вручную — цену по ней
        всё равно не рассчитать.
        """
        if not getattr(self, "_spec_mode", False):
            return False
        if item.get("is_heading"):
            return False
        bm = item.get("best_match") or {}
        article = (bm.get("article") or item.get("article_raw") or "").strip()
        code    = (bm.get("kaznisa_code")
                   or item.get("kaznisa_code_raw") or "").strip()
        return bool(article and code)

    def _price_anomaly(self, item: dict) -> str:
        """Причина, по которой ценам позиции нельзя доверять, либо "".

        Проверяются три несоответствия порядка величин: цена против
        себестоимости, сметная цена против нашей и продажа ниже закупки.
        """
        if item.get("is_heading") or item.get("has_analog_row"):
            return ""

        seb, _ss, kp, _ks = self._compute_kp(item)
        est = self._estimate_price(item)

        if seb and kp:
            if kp / seb > ANOMALY_RATIO:
                return f"цена в {kp / seb:.0f}× выше себестоимости"
            if kp < seb:
                return "цена КП ниже себестоимости"

        if est and kp:
            ratio = max(est, kp) / min(est, kp)
            if ratio > ANOMALY_RATIO:
                return f"смета и КП расходятся в {ratio:.0f}× — разные единицы?"

        if est and seb and max(est, seb) / min(est, seb) > ANOMALY_RATIO:
            return "смета и себестоимость несопоставимы"

        return ""

    def _anomaly_count(self) -> int:
        return sum(1 for it in self.items if self._price_anomaly(it))

    def _row_tag(self, item: dict) -> str:
        """Тег подсветки строки с учётом «готовности» позиции."""
        if item.get("is_heading"):
            return "heading"
        if item.get("is_analog_row"):
            return "analog"
        if item.get("has_analog_row"):
            return "orig_analog"
        _v = self._estimate_verdict(item)
        if _v == "below":
            return "est_below"
        if _v == "above":
            return "est_above"
        # Зелёный «готово» — только в режиме подбора (см. _is_ready_row)
        if self._is_ready_row(item):
            return "ready"
        status = item.get("status", "not_found")
        return {
            "exact":          "exact",
            "multiple":       "multiple",
            "fuzzy":          "multiple",
            "ai_match":       "ai",
            "manager_match":  "manager",
        }.get(status, "notfound")

    @staticmethod
    def _estimate_price(item: dict) -> float:
        """Сметная цена позиции: из сметы либо вписанная вручную."""
        try:
            return float(item.get("estimate_price") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _estimate_sum(self, item: dict) -> float:
        """Сметная сумма = сметная цена × наше количество."""
        price = self._estimate_price(item)
        if not price:
            return 0.0
        try:
            qty = float(item.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1.0
        return price * qty

    def _estimate_verdict(self, item: dict) -> str:
        """Сравнение нашей цены КП со сметной.

        'below' — наша ниже сметной (зелёная), 'above' — выше (красная),
        '' — сравнивать не с чем.
        """
        est = self._estimate_price(item)
        if not est:
            return ""
        _s, _ss, kp, _ks = self._compute_kp(item)
        if not kp:
            return ""
        if kp > est:
            return "above"
        if kp < est:
            return "below"
        return ""

    def _estimate_totals(self) -> dict:
        """Считает итоги продажи по сметным ценам.

        Берутся только позиции, у которых есть сметная цена.
        gain / loss  — разница со своей ценой КП (упущенная или добавленная выгода);
        below_cost   — позиции, где сметная цена ниже себестоимости: реальный убыток.
        """
        n = gain_n = loss_n = below_n = profit_n = 0
        sum_kp = sum_est = sum_seb = 0.0
        gain = loss = below_sum = profit_sum = 0.0

        for it in self.items:
            if it.get("is_heading") or it.get("has_analog_row"):
                continue
            est = self._estimate_price(it)
            if not est:
                continue
            try:
                qty = float(it.get("qty", 1) or 1)
            except (TypeError, ValueError):
                qty = 1.0

            seb, _ss, kp, _ks = self._compute_kp(it)
            n += 1
            sum_est += est * qty
            sum_kp  += kp * qty
            sum_seb += seb * qty

            if kp:
                if est > kp:
                    gain_n += 1
                    gain += (est - kp) * qty
                elif est < kp:
                    loss_n += 1
                    loss += (kp - est) * qty

            if seb:
                if est > seb:
                    # Продажа по смете покрывает себестоимость — позиция прибыльная
                    profit_n += 1
                    profit_sum += (est - seb) * qty
                elif est < seb:
                    below_n += 1
                    below_sum += (seb - est) * qty

        return {
            "n": n, "sum_kp": sum_kp, "sum_est": sum_est, "sum_seb": sum_seb,
            "delta": sum_est - sum_kp,
            "delta_pct": ((sum_est - sum_kp) / sum_kp * 100) if sum_kp else 0.0,
            "gain": gain, "gain_n": gain_n,
            "loss": loss, "loss_n": loss_n,
            "profit_n": profit_n, "profit_sum": profit_sum,
            "below_sum": below_sum, "below_n": below_n,
            "margin": sum_est - sum_seb,
            "margin_pct": ((sum_est - sum_seb) / sum_est * 100) if sum_est else 0.0,
        }

    def _update_estimate_summary(self):
        """Перерисовывает полосу итогов под таблицей."""
        if not hasattr(self, "est_bar"):
            return
        t = self._estimate_totals()
        if not t["n"]:
            self.est_bar.grid_remove()
            return
        self.est_bar.grid()

        def m(v):
            return f"{v:,.0f}".replace(",", " ")

        # Вердикт: убыток важнее упущенной выгоды
        if t["below_n"]:
            verdict, color = "НИЖЕ СЕБЕСТОИМОСТИ", "#C0392B"
            border = "#C0392B"
        elif t["margin"] <= 0:
            verdict, color = "В МИНУСЕ", "#C0392B"
            border = "#C0392B"
        elif t["delta"] >= 0:
            verdict, color = "В ПЛЮСЕ", "#1E8449"
            border = "#1E8449"
        else:
            verdict, color = "ПРИБЫЛЬ ЕСТЬ", "#B9770E"
            border = "#7D6608"

        self.est_verdict_lbl.configure(text=verdict, text_color=color)
        self.est_bar.configure(border_color=border)

        sign = "+" if t["delta"] >= 0 else "−"
        self.est_main_lbl.configure(
            text=(f"Продажа по сметным ценам ({t['n']} поз.):   "
                  f"наша сумма КП {m(t['sum_kp'])} ₸   →   "
                  f"по смете {m(t['sum_est'])} ₸   |   "
                  f"разница {sign}{m(abs(t['delta']))} ₸ "
                  f"({t['delta_pct']:+.1f} %)"),
            text_color=color,
        )

        parts = [
            f"Выигрываем на {t['profit_n']} поз. "
            f"(смета выше себестоимости): +{m(t['profit_sum'])} ₸",
            f"недополучаем против КП на {t['loss_n']} поз.: −{m(t['loss'])} ₸",
            f"прибыль над себестоимостью: {m(t['margin'])} ₸ "
            f"({t['margin_pct']:.1f} %)",
        ]
        if t["below_n"]:
            parts.append(
                f"⚠ ниже себестоимости {t['below_n']} поз. на {m(t['below_sum'])} ₸"
            )
        self.est_detail_lbl.configure(
            text="   ·   ".join(parts),
            text_color="#C0392B" if t["below_n"] else TEXT_SECONDARY,
        )

    def _brand_rates(self, item: dict) -> tuple:
        """Курс, НДС и логистику бренда позиции. По умолчанию — единицы."""
        bm = item.get("best_match") or {}
        bc = self.brand_consts.get((bm.get("brand") or "").upper())
        if not bc:
            try:
                return (float(self.const_vars["currency_rate"].get() or 1),
                        float(self.const_vars["nds"].get() or 1),
                        float(self.const_vars["logistics"].get() or 1))
            except (tk.TclError, ValueError, KeyError):
                return 1.0, 1.0, 1.0
        return (float(bc.get("currency_rate", 1.0) or 1.0),
                float(bc.get("nds",           1.0) or 1.0),
                float(bc.get("logistics",     1.0) or 1.0))

    def _partner_kzt(self, item: dict) -> float:
        """Цена поставщика, приведённая к тенге.

        В базе она хранится в валюте поставщика: у RUBEZH и EKF в рублях,
        у HIKVISION и HPE в долларах. Без перевода себестоимость нельзя
        сравнивать ни с ценой КазНИИСА, ни со сметой — они уже в тенге.
        """
        bm = item.get("best_match") or {}
        try:
            partner = float(bm.get("partner") or 0)
        except (TypeError, ValueError):
            return 0.0
        if not partner:
            return 0.0
        cur, nds, lo = self._brand_rates(item)
        return partner * cur * nds * lo

    def _prelim_price(self, item: dict) -> float:
        """Предварительная цена позиции.

        Правило:
          • есть код АГСК И заполнена цена КазНИИСА → берём цену КазНИИСА;
          • иначе (нет кода, либо код есть но цена пустая) →
            Партнёр/проект/дистр. × коэффициент (настройка администратора).

        Ручной ввод пользователя в колонке имеет наивысший приоритет.
        Применяется при любом типе расценки.
        """
        if item.get("_user_const_price"):
            try:
                return float(item["_user_const_price"])
            except (TypeError, ValueError):
                return 0.0

        bm = item.get("best_match") or {}
        # Код берём ТОЛЬКО у товара из БД: код из PDF (kaznisa_code_raw)
        # не подтверждает наличие позиции в прайсе КазНИИСА.
        code = (bm.get("kaznisa_code") or "").strip()
        try:
            kaz = float(bm.get("kaznisa") or 0)
        except (TypeError, ValueError):
            kaz = 0.0
        if code and kaz:
            return kaz

        # Партнёр в валюте поставщика — сначала в тенге, потом коэффициент
        partner = self._partner_kzt(item)
        if partner:
            try:
                coeff = float(self._prelim_coeff or DEFAULT_PRELIM_COEFF)
            except (TypeError, ValueError):
                coeff = DEFAULT_PRELIM_COEFF
            return partner * coeff
        return 0.0

    @staticmethod
    def _has_manual_price(item: dict) -> bool:
        """True только если пользователь ЯВНО задал цену вручную.

        Флаг _user_edited сам по себе недостаточен: он также ставится
        аналог-строкам (защита от ИИ-переподбора), а их цены обязаны
        пересчитываться при смене типа расценки.
        """
        return (item.get("_user_price")       is not None
                or item.get("_user_seb_price")   is not None
                or item.get("_user_const_price") is not None)

    def _recalc_all(self):
        """Пересчитывает цены для всех позиций (вызывается при смене расценки)."""
        for item in self.items:
            if self._has_manual_price(item):
                continue
            iid = item.get("_iid")
            if not iid or not self.tree.exists(iid):
                continue
            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            _pp = self._prelim_price(item)
            item["_prelim_price"] = _pp or None
            vals = list(self.tree.item(iid, "values"))
            vals[C_SEB]     = f"{seb:.2f}"     if seb     else ""
            vals[C_SEB_SUM] = f"{seb_sum:.2f}" if seb_sum else ""
            vals[C_KP]      = f"{kp:.2f}"      if kp      else ""
            vals[C_KP_SUM]  = f"{kp_sum:.2f}"  if kp_sum  else ""
            vals[C_PRELIM]  = f"{_pp:.2f}"     if _pp     else ""
            _es = self._estimate_sum(item)
            vals[C_EST_SUM] = f"{_es:.2f}" if _es else ""
            self.tree.item(iid, values=vals)

        self._update_estimate_summary()

    # ── Расчёт цены ──────────────────────────────────────────────────────────
    def _compute_kp(self, item: dict) -> tuple:
        """
        Возвращает (price_seb, sum_seb, price_kp, sum_kp).

        Цена себес — всегда Проектная (Партнёр/проект/дистр.) из БД.
        От выбранной расценки НЕ зависит и при её переключении не меняется.

        Цена КП — по выбранной расценке:
            base = выбор по rate-индексу бренда из БД:
                   1=Сумма АГСК, 2=Цена АГСК, 3=РРЦ, 4=МРЦ,
                   5=Опт, 6=Цена ГП (РРЦ×ГП), 7=Сумма ГП, 8=Проект
                   либо ручная предварительная цена
            price_kp = base × курс × НДС × лог-ка × маржа
                       (для АГСК курс/НДС/логистика не применяются)
            суммы    = цена × Кол-во, округление вверх.
        """
        bm    = item.get("best_match") or {}
        brand = (bm.get("brand") or "").upper()
        bc    = self.brand_consts.get(brand)
        if not bc:
            # Фолбэк — берём текущие значения с экрана
            try:
                bc = {
                    "margin":        float(self.const_vars["margin"].get()),
                    "logistics":     float(self.const_vars["logistics"].get()),
                    "nds":           float(self.const_vars["nds"].get()),
                    "currency_rate": float(self.const_vars["currency_rate"].get()),
                    "rate":          int(float(self.const_vars["rate"].get() or DEFAULT_RATE_IDX)),
                    "gp":            1.0,
                }
            except (tk.TclError, ValueError):
                return 0.0, 0.0, 0.0, 0.0

        rate_type = int(bc.get("rate", 3) or 3)
        cur = float(bc.get("currency_rate", 1.0) or 1.0)
        nds = float(bc.get("nds",           1.0) or 1.0)
        lo  = float(bc.get("logistics",     1.0) or 1.0)
        mg  = float(bc.get("margin",        1.0) or 1.0)
        qty = float(item.get("qty", 1) or 1)

        # ── Цена себес: всегда Проектная из БД, от расценки не зависит,
        # но переведённая в тенге: в базе она в валюте поставщика ──
        try:
            _partner = float(bm.get("partner") or 0)
        except (TypeError, ValueError):
            _partner = 0.0
        price_seb = math.ceil(_partner * cur * nds * lo) if _partner else 0.0

        # ── Приоритет 1: пользователь задал Цена КП напрямую ────────────
        if item.get("_user_edited") and item.get("_user_price") is not None:
            price_kp = math.ceil(float(item["_user_price"]))
            return price_seb, price_seb * qty, price_kp, price_kp * qty

        # ── Приоритет 2: пользователь задал Цена себес напрямую ─────────
        if item.get("_user_seb_price") is not None:
            price_seb = math.ceil(float(item["_user_seb_price"]))
            price_kp  = math.ceil(price_seb * mg)
            return price_seb, price_seb * qty, price_kp, price_kp * qty

        # ── База для Цены КП: ручная предварительная цена либо поле расценки ──
        if item.get("_user_const_price"):
            base = float(item["_user_const_price"])
        else:
            field = RATE_FIELD.get(rate_type, "rrts")
            base = (bm.get(field)
                    or bm.get("rrts") or bm.get("partner")
                    or bm.get("mrc")  or bm.get("opt")
                    or bm.get("kaznisa") or 0)
            if rate_type in GP_RATE_TYPES:
                gp = float(bc.get("gp", 1.0) or 1.0)
                base = float(base or 0) * gp

        base = float(base or 0)
        if not base:
            # Себестоимость показываем даже если базы для КП нет
            return price_seb, price_seb * qty, 0.0, 0.0

        if rate_type in AGSK_RATE_TYPES:
            # kaznisa / АГСК — цена уже в KZT из государственного прайса КазНИИСА.
            # Курс валюты, НДС и логистика НЕ применяются (они заложены в цене).
            _kp_base = math.ceil(base)
        else:
            _kp_base = math.ceil(base * cur * nds * lo)
        price_kp = math.ceil(_kp_base * mg)
        return price_seb, price_seb * qty, price_kp, price_kp * qty

    # ── Заполнение таблицы ───────────────────────────────────────────────────
    def _populate(self, items=None):
        self.tree.delete(*self.tree.get_children())
        data = items if items is not None else self.items
        for item in data:
            self._insert_row(item)

    def _adjust_row_height(self):
        """Set rowheight to fit the tallest cell value across all visible rows."""
        max_lines = 1
        for iid in self.tree.get_children():
            for val in self.tree.item(iid, "values"):
                lines = str(val).count("\n") + 1
                if lines > max_lines:
                    max_lines = lines
        line_px  = 15   # pixels per text line at Calibri 10
        padding  = 6    # top+bottom cell padding
        new_h    = max(23, max_lines * line_px + padding)
        ttk.Style().configure("APS.Treeview", rowheight=new_h)

    @staticmethod
    def _method_label(method: str) -> str:
        """Return a human-readable Russian label for the match method."""
        if not method:
            return ""
        _MAP = {
            "exact":                    "Артикул (точн.)",
            "contains":                 "Артикул (вхожд.)",
            "fuzzy_article":            "Артикул (нечётк.)",
            "fuzzy_name_from_article":  "Артикул (нечётк.)",
            "name_exact":               "Название (точн.)",
            "name_contains":            "Название (вхожд.)",
            "name_fuzzy":               "Название (нечётк.)",
            "name_partial":             "Название (частич.)",
            "code_exact":               "АГСК (код)",
            "kaznisa":                  "АГСК (код)",
        }
        if method in _MAP:
            return _MAP[method]
        if method == "correction_history":
            return "📚 История"
        if method.startswith("ai"):
            return "ИИ"
        return method

    def _redraw_row(self, item: dict):
        """
        Перерисовывает строку на её текущей позиции — без перемещения вниз.
        Если строка ещё не в таблице — добавляет в конец (обычный _insert_row).
        """
        old_iid = item.get("_iid")
        if old_iid and self.tree.exists(old_iid):
            pos = self.tree.index(old_iid)   # запоминаем позицию
            self.tree.delete(old_iid)
            item["_iid"] = None
            self._insert_row(item, position=pos)
        else:
            self._insert_row(item)

    def _insert_row(self, item: dict, position: object = "end") -> str:

        # ── Аналог-строка (подобранный аналог, вставляется под оригиналом) ────
        if item.get("is_analog_row"):
            bm      = item.get("best_match") or {}
            qty_raw = item.get("qty", 1)
            brand   = bm.get("brand", "")
            article = (bm.get("article", "") or "").replace("\n", " ").strip()
            name    = (bm.get("name",    "") or "").replace("\n", " ").strip()
            unit    = bm.get("unit", "шт.")
            mult    = bm.get("multiplicity") or ""
            kaznisa_code = bm.get("kaznisa_code") or ""

            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            def _f(v): return f"{v:.2f}" if v else ""

            _a_prelim = self._prelim_price(item)
            item["_prelim_price"] = _a_prelim or None

            _cb = ("☑" if id(item) in self._checked_items else "☐") if self._select_mode else ""
            pos_lbl = f"{_cb} ↳ Аналог" if _cb else "↳ Аналог"
            vals = (
                pos_lbl, brand, article, name, unit, qty_raw, mult,
                _f(seb), _f(seb_sum), _f(_a_prelim), _f(kp), _f(kp_sum),
                _f(self._estimate_price(item)), _f(self._estimate_sum(item)),
                kaznisa_code,
                item.get("comment", "") or "",
                item.get("delivery", "") or "",
                "↳ Аналог",
                "analog",
                "",
            )
            iid = self.tree.insert("", position, values=vals, tags=("analog",))
            item["_iid"] = iid
            return iid

        bm           = item.get("best_match") or {}
        status       = item.get("status", "not_found")
        match_method = item.get("match_method")

        if status == "heading":
            # Section-header row — render as a bold blue separator spanning the name column
            heading_name = item.get("name_raw", "").replace("\n", " ").strip()
            _h_cb = ("☑" if id(item) in self._checked_items else "☐") if self._select_mode else ""
            vals = (_h_cb, "", "", heading_name) + ("",) * (len(COLS) - 4)
            iid = self.tree.insert("", position, values=vals, tags=("heading",))
            item["_iid"] = iid
            return iid

        if status == "exact":
            tag, stxt = "exact",    t("status_exact")
        elif status == "multiple":
            tag, stxt = "multiple", t("status_multiple")
        elif status == "fuzzy":
            tag, stxt = "multiple", t("status_fuzzy")
        elif status == "ai_match":
            ai_conf     = item.get("ai_confidence")
            ai_low_conf = item.get("ai_low_confidence", False)
            conf_str    = f" ({ai_conf:.0%})" if ai_conf else ""
            warn_str    = " ⚠" if ai_low_conf else ""
            tag         = "ai_low" if ai_low_conf else "ai"
            stxt        = t("status_ai_match") + conf_str + warn_str
        elif status == "manager_match":
            tag, stxt = "manager", t("status_manager_match")
        else:
            tag, stxt = "notfound", t("status_nf")

        if item.get("_user_edited"):
            tag = "edited"

        # Есть и артикул, и код АГСК — позиция готова, подсвечиваем зелёным
        if self._is_ready_row(item):
            tag = "ready"

        # Оригинал, замещённый аналогом — показываем серым, без цен
        if item.get("has_analog_row"):
            tag = "orig_analog"

        seb, seb_sum, kp, kp_sum = self._compute_kp(item)
        # Все цены замещённой позиции показываются на строке аналога.
        # Сметная — тоже: иначе строка выглядит как позиция со сметой,
        # но без себестоимости, и сравнивать её не с чем.
        _est_p = self._estimate_price(item)
        _est_s = self._estimate_sum(item)
        if item.get("has_analog_row"):
            seb = seb_sum = kp = kp_sum = 0.0
            _est_p = _est_s = 0.0
        qty_raw = item.get("qty", 1)
        brand = bm.get("brand", "")
        article = (bm.get("article", "") or item.get("article_raw", "")).replace("\n", " ").strip()
        name    = (bm.get("name",    "") or item.get("name_raw", "")).replace("\n", " ").strip()
        unit    = bm.get("unit", "шт.") if bm else "шт."
        mult    = bm.get("multiplicity") or ""

        # Предупреждение о несовпадении единиц: PDF-единица vs единица в БД
        pdf_unit = (item.get("unit") or "").strip().lower()
        db_unit  = unit.strip().lower()
        if pdf_unit and bm and pdf_unit != db_unit and pdf_unit not in ("шт", "шт.", ""):
            qty = f"{qty_raw} ({item.get('unit', '')}≠{unit})"
        else:
            qty = qty_raw
        # Если товар найден — берём код из БД; если нет — показываем код из PDF
        kaznisa_code = bm.get("kaznisa_code") or item.get("kaznisa_code_raw", "") or ""
        # Предварительная цена: КазНИИСА либо Партнёр × коэффициент
        _prelim = self._prelim_price(item)
        item["_prelim_price"] = _prelim or None
        const_price = f"{_prelim:.2f}" if _prelim else ""

        def f(v):
            return f"{v:.2f}" if v else ""

        method_lbl = self._method_label(match_method)

        # Detect matched items with no price in DB → annotate method label
        _price_fields = ("kaznisa", "rrts", "mrc", "opt", "partner")
        _no_price_in_db = (
            bool(bm)
            and status not in ("not_found",)
            and not any(bm.get(f) for f in _price_fields)
            and not item.get("_user_const_price")
            and not item.get("_user_price")
        )
        if _no_price_in_db:
            method_lbl = (method_lbl + " | нет цены в БД") if method_lbl else "нет цены в БД"

        if item.get("has_analog_row"):
            method_lbl = "↓ аналог подобран"

        _anomaly = self._price_anomaly(item)
        if _anomaly:
            method_lbl = f"{method_lbl} | ⚠ {_anomaly}" if method_lbl else f"⚠ {_anomaly}"

        _pos_raw = item.get("pos", "")
        if self._select_mode:
            _cb = "☑" if id(item) in self._checked_items else "☐"
            _pos_display = f"{_cb} {_pos_raw}" if _pos_raw else _cb
        else:
            _pos_display = _pos_raw
        if _anomaly:
            _pos_display = f"⚠ {_pos_display}".strip()
        vals = (
            _pos_display,
            brand,
            article,
            name,
            unit,
            qty,
            mult,
            f(seb),
            f(seb_sum),
            const_price,
            f(kp),
            f(kp_sum),
            f(_est_p),
            f(_est_s),
            kaznisa_code,
            item.get("comment", "") or "",
            item.get("delivery", "") or "",
            stxt,
            method_lbl,
            item.get("_analog_art", ""),
        )
        # Сравнение со сметой важнее прочей окраски — но не для замещённой
        # позиции: её цены на строке аналога, и вердикт относится к ней же.
        if not item.get("has_analog_row"):
            _verdict = self._estimate_verdict(item)
            if _verdict == "below":
                tag = "est_below"
            elif _verdict == "above":
                tag = "est_above"

        _tags = (tag, "anomaly") if _anomaly else (tag,)
        iid = self.tree.insert("", position, values=vals, tags=_tags)
        item["_iid"] = iid
        return iid

    def _refresh_analog_col(self):
        """После populate — асинхронно загружает аналоги из БД и вставляет в колонку c17."""
        # Собираем уникальные артикулы из items (только не-heading, не-analog строки)
        art_to_iids: dict[str, list] = {}
        for it in self.items:
            if it.get("is_analog_row") or it.get("status") == "heading":
                continue
            bm  = it.get("best_match") or {}
            art = (bm.get("article") or it.get("article_raw", "")).replace("\n", " ").strip()
            if not art:
                continue
            iid = it.get("_iid")
            if not iid:
                continue
            art_to_iids.setdefault(art, []).append((iid, it))

        if not art_to_iids:
            return

        articles = list(art_to_iids.keys())
        segment  = getattr(getattr(self, "app", None), "config", None)
        segment  = getattr(segment, "user_segment", "ss") or "ss"

        def _worker():
            try:
                analogs = self.api.lookup_analogs_batch(articles, segment=segment)
            except Exception:
                try:
                    analogs = self.api.lookup_analogs_batch(articles)
                except Exception:
                    return
            self.after(0, lambda a=analogs: self._apply_analog_col(a, art_to_iids))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_analog_col(self, analogs: dict, art_to_iids: dict):
        """Применяет результат lookup к колонке c17 в дереве."""
        for art, entries in art_to_iids.items():
            info = analogs.get(art)
            analog_art = info["analog_article"] if info else ""
            for iid, item in entries:
                item["_analog_art"] = analog_art
                try:
                    vals = list(self.tree.item(iid, "values"))
                    while len(vals) < 18:
                        vals.append("")
                    vals[17] = analog_art
                    self.tree.item(iid, values=vals)
                except Exception:
                    pass

    def _update_stats(self):
        # Exclude section-header rows and analog sub-rows from all counters
        total    = sum(1 for i in self.items if i.get("status") != "heading" and not i.get("is_analog_row"))
        exact    = sum(1 for i in self.items if i.get("status") == "exact")
        warn     = sum(1 for i in self.items if i.get("status") in ("multiple", "fuzzy"))
        ai_match = sum(1 for i in self.items if i.get("status") == "ai_match")
        ai_low   = sum(1 for i in self.items if i.get("ai_low_confidence"))
        nf       = sum(1 for i in self.items if i.get("status") == "not_found")
        downgraded  = sum(1 for i in self.items if i.get("ai_downgraded"))
        manager_m   = sum(1 for i in self.items if i.get("status") == "manager_match")
        corrected   = sum(1 for i in self.items if i.get("_corrected_by_manager"))
        # Count matched items that have no price in DB
        no_price = sum(
            1 for i in self.items
            if i.get("best_match") and i.get("status") not in ("not_found",)
            and not any(
                i.get("best_match", {}).get(f)
                for f in ("kaznisa", "rrts", "mrc", "opt", "partner")
            )
        )
        stat_text = t("preview_stat", total=total, exact=exact, warn=warn, nf=nf)
        if manager_m:
            stat_text += t("preview_stat_manager", count=manager_m)
        if ai_match:
            stat_text += t("preview_stat_ai", count=ai_match)
            if ai_low:
                stat_text += t("preview_stat_ai_low", count=ai_low)
        if downgraded:
            stat_text += t("preview_stat_downgraded", count=downgraded)
        if corrected:
            stat_text += t("preview_stat_corrected", count=corrected)
        if no_price:
            stat_text += t("preview_stat_no_price", count=no_price)
        _anom = self._anomaly_count()
        if _anom:
            stat_text += f"   ⚠ требуют проверки цен: {_anom}"
        self.stat_lbl.configure(text=stat_text)
        self._update_estimate_summary()

    # ── Реакция на изменение констант ────────────────────────────────────────
    def _on_const_change(self, *_):
        if self._suppress_recalc:
            return
        brand = self.brand_var.get().strip().upper()
        if not brand or brand == "—":
            return
        # Обновляем словарь констант для бренда из полей
        try:
            bc = self.brand_consts.setdefault(brand, {})
            bc["margin"]        = float(self.const_vars["margin"].get())
            bc["logistics"]     = float(self.const_vars["logistics"].get())
            bc["nds"]           = float(self.const_vars["nds"].get())
            bc["currency_rate"] = float(self.const_vars["currency_rate"].get())
            bc["rate"]          = int(float(self.const_vars["rate"].get() or DEFAULT_RATE_IDX))
        except (tk.TclError, ValueError):
            return
        self._recalc_for_brand(brand)

    def _recalc_for_brand(self, brand: str):
        for item in self.items:
            bm = item.get("best_match") or {}
            if (bm.get("brand") or "").upper() != brand:
                continue
            if self._has_manual_price(item):
                continue
            iid = item.get("_iid")
            if not iid or not self.tree.exists(iid):
                continue
            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            _pp = self._prelim_price(item)
            item["_prelim_price"] = _pp or None
            vals = list(self.tree.item(iid, "values"))
            vals[C_SEB]     = f"{seb:.2f}"      if seb     else ""
            vals[C_SEB_SUM] = f"{seb_sum:.2f}"  if seb_sum else ""
            vals[C_KP]      = f"{kp:.2f}"       if kp      else ""
            vals[C_KP_SUM]  = f"{kp_sum:.2f}"   if kp_sum  else ""
            vals[C_PRELIM]  = f"{_pp:.2f}"      if _pp     else ""
            _es = self._estimate_sum(item)
            vals[C_EST_SUM] = f"{_es:.2f}" if _es else ""
            self.tree.item(iid, values=vals)
        self._update_estimate_summary()

    # ── Фильтр и поиск ───────────────────────────────────────────────────────
    def _set_filter(self, mode: str):
        self._filter_mode = mode
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == mode else "#AEB6BF")
        self._apply_filter()

    def _on_search(self, *_):
        self._apply_filter()

    def _apply_filter(self):
        q = self.search_var.get().lower().strip()
        result = []
        for item in self.items:
            status = item.get("status", "not_found")
            # Section-header rows always pass through filters (they provide context)
            if status == "heading":
                result.append(item)
                continue
            if self._filter_mode == "warn" and status not in ("multiple", "fuzzy"):
                continue
            if self._filter_mode == "nf" and status != "not_found":
                continue
            if q and q not in (item.get("article_raw","") + item.get("name_raw","")).lower():
                continue
            result.append(item)
        self._populate(result)

    # ── Одиночный клик / завершение редактирования ──────────────────────────
    def _on_row_select(self, event=None):
        """Показывает сырые цены из БД и техпараметры в строке статуса при выборе строки."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = next((i for i in self.items if i.get("_iid") == iid), None)
        if not item:
            return
        bm = item.get("best_match") or {}

        # Форматируем цены из БД
        def _fmt(v):
            if v is None: return "—"
            try: return f"{float(v):,.0f}"
            except: return str(v)

        parts = []

        if bm:
            brand   = bm.get("brand") or "не задан"
            kaznisa = _fmt(bm.get("kaznisa"))
            rrts    = _fmt(bm.get("rrts"))
            mrc     = _fmt(bm.get("mrc"))
            opt     = _fmt(bm.get("opt"))
            partner = _fmt(bm.get("partner"))
            parts.append(
                f"{t('preview_info_db')}: [{bm.get('article','')}] Бренд={brand}  "
                f"АГСК={kaznisa}  РРЦ={rrts}  МРЦ={mrc}  Опт={opt}  Проект={partner}"
            )

        # Техпараметры (Phase 2.2)
        tech_params = item.get("tech_params") or {}
        if tech_params:
            tp_str = "  ".join(f"{k}: {v}" for k, v in list(tech_params.items())[:6])
            parts.append(f"{t('preview_info_tech')}: {tp_str}")

        # AI reason / confidence
        ai_reason = item.get("ai_reason") or ""
        ai_conf   = item.get("ai_confidence")
        if ai_reason and item.get("ai_used"):
            conf_str = f" ({ai_conf:.0%})" if ai_conf else ""
            parts.append(f"{t('preview_info_ai')}: {ai_reason}{conf_str}")

        if not parts:
            return

        info = "   |   ".join(parts)
        self.stat_lbl.configure(text=info, text_color="#E67E22")

    def _on_tree_single_click(self, event):
        """Одиночный клик по таблице: если активно inline-поле — сохраняем его."""
        if self._edit_entry and self._edit_iid:
            self._commit_edit(self._edit_entry)
        if self._select_mode:
            region = self.tree.identify_region(event.x, event.y)
            col    = self.tree.identify_column(event.x)
            if col == "#1":   # колонка № — переключаем чекбокс
                if region == "heading":
                    self._select_all_toggle()
                    return "break"
                elif region == "cell":
                    iid = self.tree.identify_row(event.y)
                    if iid:
                        self._toggle_item_check(iid)
                    return "break"
        # НЕ возвращаем "break" — обычная выборка строки продолжается

    # ── Двойной клик ─────────────────────────────────────────────────────────
    def _on_double_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        col_idx = int(col.replace("#", "")) - 1
        if not iid:
            return
        item = self._get_item_by_iid(iid)
        if item is None:
            return

        # Жёлтая строка + клик по нередактируемой колонке → выбор кандидата
        if item.get("status") in ("multiple", "fuzzy", "ai_match", "manager_match") and col_idx not in EDITABLE_COLS:
            cands = item.get("candidates", [])
            if cands:
                dlg = CandidateDialog(self, cands)
                self.wait_window(dlg)
                if dlg.selected:
                    self._apply_correction(item, iid, dlg.selected, confirm_only=False)
            return

        # Красная строка + клик по нередактируемой колонке → поиск в БД
        if item.get("status") == "not_found" and col_idx not in EDITABLE_COLS:
            self._open_article_search(item, iid)
            return

        if col_idx in EDITABLE_COLS:
            self._start_edit(iid, col, col_idx, item)
        elif item.get("status") in ("multiple", "fuzzy", "ai_match", "manager_match"):
            cands = item.get("candidates", [])
            if cands:
                dlg = CandidateDialog(self, cands)
                self.wait_window(dlg)
                if dlg.selected:
                    self._apply_correction(item, iid, dlg.selected, confirm_only=False)
        elif item.get("status") == "not_found":
            self._open_article_search(item, iid)

    def _get_item_by_iid(self, iid: str) -> Optional[Dict]:
        for item in self.items:
            if item.get("_iid") == iid:
                return item
        return None

    # ── Phase 2.6: Исправления менеджеров ───────────────────────────────────

    def _apply_correction(self, item: dict, iid: str, selected_product: dict, confirm_only: bool = False):
        """
        Применяет выбор менеджера к строке и записывает исправление.
        confirm_only=True — просто подтверждает текущий матч без смены товара.
        confirm_only=False — меняет best_match на selected_product.
        """
        orig_status = item.get("status", "not_found")

        if not confirm_only:
            # Применяем выбранный товар
            item["best_match"] = selected_product
            item["status"]     = "exact"
            item["_user_edited"] = False
            item["_user_price"]  = None
            item["_corrected_by_manager"] = True

        # Записываем исправление в фоне (не блокируем UI)
        product_id = (selected_product or item.get("best_match") or {}).get("id")
        if product_id:
            orig_name    = item.get("name_raw", "") or ""
            orig_article = item.get("article_raw", "") or ""

            def _record():
                try:
                    self.api.record_correction(
                        original_name       = orig_name,
                        original_article    = orig_article,
                        original_status     = orig_status,
                        selected_product_id = int(product_id),
                        session_id          = self._session_id,
                    )
                except Exception as e:
                    print(f"[Correction] record failed: {e}")

            import threading
            threading.Thread(target=_record, daemon=True).start()

        if not confirm_only:
            # Перерисовываем строку с зелёным статусом (на том же месте)
            self._redraw_row(item)
        else:
            # Только подтверждение — отмечаем флагом, обновляем метод
            item["_corrected_by_manager"] = True
            item["match_method"] = "confirmed"
            if iid and self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals[16] = "✓ " + (vals[16] or "")
                self.tree.item(iid, values=vals)

        self._update_stats()

    def _confirm_selected_row(self):
        """Контекстное меню: подтвердить текущий подбор (обучает модель)."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = self._get_item_by_iid(iid)
        if not item:
            return
        bm = item.get("best_match")
        if not bm or not bm.get("id"):
            messagebox.showinfo(t("search_dialog_title"), "Нет подобранного товара для подтверждения.")
            return
        self._apply_correction(item, iid, bm, confirm_only=True)

    def _search_and_replace_selected(self):
        """Контекстное меню: поиск товара в БД по артикулу/названию."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = self._get_item_by_iid(iid)
        if item:
            self._open_article_search(item, iid)

    def _open_article_search(self, item: dict, iid: str):
        """Открывает ArticleSearchDialog для поиска замены товара."""
        segment = getattr(self.app.config, "user_segment", "ss") or "ss"
        dlg = ArticleSearchDialog(self, self.api, item, default_segment=segment)
        self.wait_window(dlg)
        if dlg.selected:
            self._apply_correction(item, iid, dlg.selected, confirm_only=False)

    def _refresh_row(self, iid: str, item: dict):
        # Полная перерисовка строки после смены кандидата
        seb, seb_sum, kp, kp_sum = self._compute_kp(item)
        bm    = item.get("best_match") or {}
        brand = bm.get("brand", "")
        vals = (
            item.get("pos", ""),
            brand,
            bm.get("article", ""),
            (bm.get("name", "") or "")[:80],
            bm.get("unit", "шт."),
            item.get("qty", 1),
            bm.get("multiplicity") or "",
            item.get("_user_const_price") or "",
            f"{seb:.2f}"      if seb     else "",
            f"{seb_sum:.2f}"  if seb_sum else "",
            f"{kp:.2f}"       if kp      else "",
            f"{kp_sum:.2f}"   if kp_sum  else "",
            bm.get("kaznisa_code") or item.get("kaznisa_code_raw", "") or "",
            item.get("comment", "") or "",
            item.get("delivery", "") or "",
            t("status_exact"),
            self._method_label(item.get("match_method")),
        )
        self.tree.item(iid, values=vals, tags=("exact",))
        try:
            self.tree.selection_remove(iid)
        except Exception:
            pass

    # ── Inline-редактирование ───────────────────────────────────────────────
    def _start_edit(self, iid, col, col_idx, item):
        self._cancel_edit()
        bbox = self.tree.bbox(iid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        cur_val = self.tree.item(iid, "values")[col_idx]
        self._edit_iid  = iid
        self._edit_col  = col_idx
        self._edit_item = item

        entry = tk.Entry(self.tree, font=("Calibri", 10), relief="solid", bd=1)
        entry.insert(0, cur_val)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.bind("<Return>",   lambda e: self._commit_edit(entry))
        entry.bind("<Escape>",   lambda e: self._cancel_edit())

        # Меню буфера не должно завершать редактирование по FocusOut
        self._edit_menu_open = False

        def _on_focus_out(_e):
            if getattr(self, "_edit_menu_open", False):
                return
            self._commit_edit(entry)

        entry.bind("<FocusOut>", _on_focus_out)

        _menu = tk.Menu(entry, tearoff=0)
        _menu.add_command(label="Вставить",
                          command=lambda: entry.event_generate("<<Paste>>"))
        _menu.add_command(label="Копировать",
                          command=lambda: entry.event_generate("<<Copy>>"))
        _menu.add_command(label="Вырезать",
                          command=lambda: entry.event_generate("<<Cut>>"))

        def _popup(ev):
            self._edit_menu_open = True
            try:
                _menu.tk_popup(ev.x_root, ev.y_root)
            finally:
                _menu.grab_release()
                self.after(50, lambda: setattr(self, "_edit_menu_open", False))
                entry.focus_set()

        entry.bind("<Button-3>", _popup)
        self._edit_entry = entry

    def _commit_edit(self, entry):
        if not self._edit_iid:
            return
        try:
            raw = entry.get().strip()
        except Exception:
            self._cancel_edit()
            return
        iid     = self._edit_iid
        col_idx = self._edit_col
        item    = self._edit_item
        vals    = list(self.tree.item(iid, "values"))

        bm = item.setdefault("best_match", {}) or {}
        item["best_match"] = bm

        if col_idx == 6:
            try:
                bm["multiplicity"] = int(float(raw.replace(",", "."))) if raw else None
            except ValueError:
                pass
            vals[6] = bm.get("multiplicity") or ""

        elif col_idx == C_EST_PRICE:
            # Сметную цену можно вписать вручную, если подобрать не удалось
            try:
                val = float((raw or "0").replace(",", ".").replace(" ", ""))
            except ValueError:
                self._cancel_edit()
                return
            item["estimate_price"] = val if val > 0 else None
            if val > 0:
                item["estimate_match"] = "manual"
            else:
                item.pop("estimate_match", None)
            vals[C_EST_PRICE] = f"{val:.2f}" if val else ""
            _es = self._estimate_sum(item)
            vals[C_EST_SUM] = f"{_es:.2f}" if _es else ""
            self.tree.item(iid, values=vals, tags=(self._row_tag(item),))
            self._cancel_edit()
            return

        elif col_idx in (C_ARTICLE, C_KAZ_CODE):
            # Артикул и код АГСК — текст. Пишем и в позицию, и в подобранный
            # товар, чтобы значение ушло в обратную запись в спецификацию.
            text = raw.strip()
            if col_idx == C_ARTICLE:
                item["article_raw"] = text
                bm["article"] = text
                item["_user_article"] = bool(text)
            else:
                item["kaznisa_code_raw"] = text
                bm["kaznisa_code"] = text
                item["_user_kaznisa_code"] = bool(text)
            vals[col_idx] = text
            # Пересчитываем подсветку: значение могло достроить позицию до «готовой»
            self.tree.item(iid, values=vals, tags=(self._row_tag(item),))
            self._cancel_edit()
            return

        elif col_idx in (13, 14):
            key = "comment" if col_idx == 13 else "delivery"
            item[key] = raw
            vals[col_idx] = raw

        else:
            try:
                # Очищаем предупреждение "(м≠упак)" если оно есть в ячейке
                clean_raw = raw.split("(")[0].strip() if "(" in raw else raw
                new_val = float(clean_raw.replace(",", ".")) if clean_raw else 0.0
            except ValueError:
                self._cancel_edit()
                return
            if col_idx == 5:
                item["qty"] = new_val
                # После ручной правки qty — сбрасываем unit чтобы убрать предупреждение (м≠упак)
                bm_unit = (item.get("best_match") or {}).get("unit", "")
                if bm_unit:
                    item["unit"] = bm_unit
            elif col_idx == C_PRELIM:
                # Предварительная цена — ручное переопределение
                item["_user_const_price"] = new_val if new_val else None
                item["_user_seb_price"]   = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == C_SEB:
                item["_user_seb_price"]   = new_val if new_val else None
                item["_user_const_price"] = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == C_SEB_SUM:
                qty_v = float(item.get("qty", 1) or 1)
                item["_user_seb_price"]   = (new_val / qty_v) if (new_val and qty_v) else None
                item["_user_const_price"] = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == C_KP:
                item["_user_edited"] = True
                item["_user_price"]  = new_val
            elif col_idx == C_KP_SUM:
                qty_v = float(item.get("qty", 1) or 1)
                item["_user_edited"] = True
                item["_user_price"]  = (new_val / qty_v) if (new_val and qty_v) else None
            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            _pp = self._prelim_price(item)
            item["_prelim_price"] = _pp or None
            vals[5]         = item.get("qty", 1)
            vals[C_SEB]     = f"{seb:.2f}"     if seb     else ""
            vals[C_SEB_SUM] = f"{seb_sum:.2f}" if seb_sum else ""
            vals[C_KP]      = f"{kp:.2f}"      if kp      else ""
            vals[C_KP_SUM]  = f"{kp_sum:.2f}"  if kp_sum  else ""
            vals[C_PRELIM]  = f"{_pp:.2f}"     if _pp     else ""
            # Кол-во могло измениться — сметная сумма пересчитывается от него
            _es = self._estimate_sum(item)
            vals[C_EST_SUM] = f"{_es:.2f}" if _es else ""

        is_edited = bool(item.get("_user_edited") or item.get("_user_const_price") or item.get("_user_seb_price"))
        if is_edited:
            self.tree.item(iid, values=vals, tags=("edited",))
        else:
            cur_tags = self.tree.item(iid, "tags")
            self.tree.item(iid, values=vals, tags=cur_tags)
        self._cancel_edit()
        self._update_estimate_summary()

    def _cancel_edit(self, event=None):
        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None
        self._edit_iid = None

    # ── Контекстное меню / копирование ───────────────────────────────────────
    def _show_ctx_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _copy_cell(self, col_key: str):
        sel = self.tree.selection()
        if not sel:
            return
        col_ids = [c for c, _ in COLS]
        if col_key not in col_ids:
            return
        values = self.tree.item(sel[0], "values")
        col_idx = col_ids.index(col_key)
        value = values[col_idx] if col_idx < len(values) else ""
        self.clipboard_clear()
        self.clipboard_append(str(value))

    def _copy_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        col_ids = [c for c, _ in COLS]
        values = self.tree.item(sel[0], "values")
        art_idx = col_ids.index("article")
        kaz_idx = col_ids.index("kaznisa")
        art  = values[art_idx]  if art_idx  < len(values) else ""
        code = values[kaz_idx]  if kaz_idx  < len(values) else ""
        self.clipboard_clear()
        self.clipboard_append(f"{art}\t{code}")

    # ── ИИ-переподбор ────────────────────────────────────────────────────────
    def _attach_estimate(self, path: str = ""):
        """Прикрепляет смету генподрядчика и проставляет сметные цены."""
        if not self.items:
            messagebox.showinfo("", "Сначала загрузите спецификацию.")
            return

        if not path:
            path = filedialog.askopenfilename(
                title="Выберите сметный лист",
                filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Все файлы", "*.*")],
            )
        if not path:
            return

        self.attach_est_btn.configure(state="disabled", text="Разбор сметы...")

        import threading

        def _work():
            try:
                # Отправляем только то, что нужно для сопоставления.
                # _est_key возвращается сервером нетронутым и связывает
                # ответ со строкой независимо от порядка в списке.
                payload = []
                for k, it in enumerate(self.items):
                    it["_est_key"] = k
                    payload.append({
                        "_est_key":         k,
                        "is_heading":       it.get("is_heading", False),
                        "article_raw":      it.get("article_raw", ""),
                        "kaznisa_code_raw": it.get("kaznisa_code_raw", ""),
                        "name_raw":         it.get("name_raw", ""),
                        "best_match":       it.get("best_match") or {},
                    })
                res = self.api.parse_estimate(path, payload)
            except Exception as e:
                self.after(0, lambda: (
                    messagebox.showerror("Смета", str(e)),
                    self.attach_est_btn.configure(
                        state="normal", text="📎 Прикрепить сметный лист"),
                ))
                return
            self.after(0, lambda: self._on_estimate_ready(path, res))

        threading.Thread(target=_work, daemon=True).start()

    def _on_estimate_ready(self, path: str, res: dict):
        """Переносит сметные цены в позиции и перерисовывает таблицу."""
        self.attach_est_btn.configure(
            state="normal", text="📎 Прикрепить сметный лист")

        returned = res.get("items") or []

        # Сопоставляем по ключу, а не по позиции: пока шёл разбор, в списке
        # могли появиться строки аналогов и всё бы съехало на строку вниз
        by_key = {it.get("_est_key"): it for it in self.items
                  if it.get("_est_key") is not None}

        # Цены предыдущей сметы убираем — иначе останутся строки от неё
        for it in self.items:
            for k in ("estimate_price", "estimate_price_net",
                      "estimate_match", "estimate_name"):
                it.pop(k, None)

        n = skipped = 0
        for got in returned:
            price = got.get("estimate_price")
            if not price:
                continue
            it = by_key.get(got.get("_est_key"))
            if it is None:
                skipped += 1
                continue
            it["estimate_price"]     = price
            it["estimate_price_net"] = got.get("estimate_price_net")
            it["estimate_match"]     = got.get("estimate_match", "")
            it["estimate_name"]      = got.get("estimate_name", "")
            n += 1

        if skipped:
            print(f"[Смета] {skipped} цен не нашли свою строку — список изменился")

        # Цены замещённых позиций живут на строках аналогов
        self._sync_analog_estimates()

        self._estimate_path  = path
        self._estimate_stats = {**(res.get("stats") or {}),
                                **(res.get("match") or {})}

        self._populate()
        self._update_stats()

        st = res.get("match") or {}
        ps = res.get("stats") or {}

        # Сколько наших позиций вообще пригодны для связывания
        own_codes = sum(
            1 for it in self.items
            if not it.get("is_heading")
            and ((it.get("best_match") or {}).get("kaznisa_code")
                 or it.get("kaznisa_code_raw"))
        )

        head = (f"Файл: {os.path.basename(path)}\n"
                f"Листов обработано: {ps.get('sheets_used', 0)}, "
                f"позиций в смете: {ps.get('items', 0)} "
                f"(с кодом АГСК: {ps.get('with_code', 0)})\n\n")

        if n == 0:
            messagebox.showwarning(
                "Сметные цены не проставлены",
                head +
                "Ни одна позиция не совпала со сметой.\n\n"
                "Вероятные причины:\n"
                f"  • смета относится к другому проекту — коды АГСК "
                f"не пересекаются;\n"
                f"  • в спецификации мало кодов АГСК "
                f"(сейчас с кодом: {own_codes} из "
                f"{sum(1 for i in self.items if not i.get('is_heading'))});\n"
                "  • в смете нужные листы не помечены Q9, G9, K9 или РС.\n\n"
                "Сметные цены можно вписать вручную в колонке «Сметная цена».",
            )
            return

        messagebox.showinfo(
            "Смета прикреплена",
            head +
            f"Проставлено цен: {n}\n"
            f"   по коду АГСК: {st.get('by_code', 0)}\n"
            f"   по артикулу: {st.get('by_article', 0)}\n"
            f"   по наименованию: {st.get('by_name', 0)}\n"
            f"Без сметной цены: {st.get('unmatched', 0)} — "
            f"их можно заполнить вручную в колонке «Сметная цена».",
        )

    def _sync_analog_estimates(self):
        """Переносит сметные цены с замещённых позиций на их аналоги.

        Смету могли прикрепить уже после подбора аналога — тогда цена
        осталась бы на строке без цен.
        """
        by_parent = {id(it): it for it in self.items if not it.get("is_analog_row")}
        for a in self.items:
            if not a.get("is_analog_row"):
                continue
            parent = by_parent.get(a.get("_analog_parent_id"))
            if not parent:
                continue
            for k in ("estimate_price", "estimate_price_net",
                      "estimate_match", "estimate_name"):
                if parent.get(k) is not None and a.get(k) is None:
                    a[k] = parent[k]

    def _apply_estimate_prices(self):
        """Кнопка «Сметные цены»: переносит сметные цены в Цену КП."""
        rows = [it for it in self.items
                if not it.get("is_heading") and self._estimate_price(it)]
        if not rows:
            messagebox.showinfo(
                "Сметные цены",
                "Нет позиций со сметной ценой.\n"
                "Прикрепите сметный лист или заполните цены вручную.",
            )
            return

        if not messagebox.askyesno(
            "Сметные цены",
            f"Заменить цену КП на сметную для {len(rows)} позиций?\n\n"
            f"Итоговая сумма КП пересчитается по сметным ценам "
            f"и в этом виде попадёт в лист КП.",
        ):
            return

        for it in rows:
            price = self._estimate_price(it)
            it["_user_edited"] = True
            it["_user_price"]  = price

        self._populate()
        self._update_stats()

        total = sum(self._estimate_sum(it) for it in rows)
        messagebox.showinfo(
            "Сметные цены применены",
            f"Обновлено позиций: {len(rows)}\n"
            f"Сумма по сметным ценам: {total:,.2f} тг".replace(",", " "),
        )

    def _rematch_ai_all(self):
        targets = [
            item for item in self.items
            if item.get("status") in ("multiple", "fuzzy", "not_found")
            and not item.get("_user_edited")
        ]
        if not targets:
            messagebox.showinfo("", "Нет строк для переподбора ИИ.")
            return
        self._run_rematch(targets)

    def _rematch_ai_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = self._get_item_by_iid(sel[0])
        if item is None:
            return
        self._run_rematch([item])

    def _run_rematch(self, targets: list):
        payload = [
            {
                "name_raw":    it.get("name_raw", ""),
                "article_raw": it.get("article_raw", ""),
                "qty":         it.get("qty", 1),
                "pos":         it.get("pos", ""),
            }
            for it in targets
        ]

        def _worker():
            try:
                resp = self.api.rematch_ai(payload)
                results = resp.get("items", [])
                self.after(0, lambda: self._apply_rematch(targets, results))
            except Exception as e:
                self.after(0, lambda: self._rematch_error(str(e)))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_rematch(self, targets: list, results: list):
        for item, new_data in zip(targets, results):
            for key in ("status", "best_match", "candidates",
                        "match_method", "ai_confidence", "ai_used", "ai_reason",
                        "ai_low_confidence", "ai_downgraded"):
                if key in new_data:
                    item[key] = new_data[key]
            self._redraw_row(item)
        self._update_stats()

    def _rematch_error(self, error: str):
        messagebox.showerror("ИИ-переподбор", f"Ошибка:\n{error}")

    def _reset_item_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = self._get_item_by_iid(sel[0])
        if item is None:
            return
        for key in ("best_match", "candidates", "match_method",
                    "ai_confidence", "ai_used", "ai_reason",
                    "_user_edited", "_user_const_price",
                    "_corrected_by_manager",
                    "comment", "delivery"):
            item.pop(key, None)
        item["status"] = "not_found"
        self._redraw_row(item)
        self._update_stats()

    # Аналог –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

    def _find_analog_selected(self):
        """Открывает диалог подбора аналога для выделенной позиции."""
        sel = self.tree.selection()
        if not sel:
            return
        iid  = sel[0]
        # Дерево хранит iid в item["_iid"] (автогенерированный tkinter id)
        item = next((i for i in self.items if i.get("_iid") == iid), None)
        if item is None or item.get("status") == "heading":
            return
        # Артикул: из best_match (приоритет) → из оригинального PDF
        # Если артикул не найден — открываем диалог с пустым полем (ручной ввод)
        article = ((item.get("best_match") or {}).get("article")
                   or item.get("article") or "")
        article = article.strip()
        # Сегмент берём из конфига приложения
        segment = getattr(getattr(self, "app", None), "config", None)
        segment = getattr(segment, "user_segment", "ss") or "ss"
        AnalogDialog(
            parent=self,
            article=article,
            segment=segment,
            api_service=self.api,
            on_apply=lambda match, _item=item, _art=article, _seg=segment: self._apply_analog_match(_item, match, _art, _seg),
        )

    def _apply_analog_match(self, item: dict, db_match: dict,
                            orig_article: str = "", segment: str = "ss"):
        """Вставляет аналог-строку под оригинальной позицией.

        Оригинал остаётся видимым (для понимания менеджерами), получает тег
        has_analog_row=True и теряет цены. Новая аналог-строка (is_analog_row=True)
        вставляется сразу после оригинала в self.items — она несёт цены и попадает в КП.

        Дополнительно: сохраняет выбор в analog_database (постоянная БД аналогов),
        чтобы колонка «Аналог» заполнялась автоматически при следующих загрузках.
        """
        # Сохраняем аналог в постоянную БД (фон, не блокируем UI)
        analog_article_for_db = db_match.get("article", "").strip()
        if orig_article and analog_article_for_db:
            def _save_analog_db():
                try:
                    self.api.save_analog_db(
                        article=orig_article,
                        analog_article=analog_article_for_db,
                        segment=segment or "ss",
                        analog_name=db_match.get("name"),
                        analog_brand=db_match.get("brand"),
                        source="manual",
                    )
                except Exception:
                    pass  # не блокируем UI при сетевой ошибке
            import threading
            threading.Thread(target=_save_analog_db, daemon=True).start()

        # Убираем существующую аналог-строку если была (повторный вызов)
        old_analog = next(
            (i for i in self.items if i.get("is_analog_row") and i.get("_analog_parent_id") == id(item)),
            None,
        )
        if old_analog:
            self.items.remove(old_analog)

        # Помечаем оригинал как замещённый
        item["has_analog_row"] = True
        item["_user_edited"]   = True
        # Сбрасываем старые ценовые артефакты у оригинала
        for k in ("_user_const_price", "_user_price", "_user_seb_price", "ai_confidence", "ai_reason"):
            item.pop(k, None)

        # Создаём аналог-строку
        analog_item: dict = {
            "is_analog_row":     True,
            "_analog_parent_id": id(item),
            "best_match":        db_match,
            "status":            "analog",
            "match_method":      "analog",
            "qty":               item.get("qty", 1),
            "unit":              (db_match.get("unit") or item.get("unit") or "шт."),
            "pos":               "",
            "name_raw":          db_match.get("name", ""),
            "article_raw":       db_match.get("article", ""),
            "_user_edited":      True,
        }
        # Смета сопоставлена с оригиналом (у него код и артикул), а цены
        # теперь на аналоге — переносим, чтобы сравнение осталось парным
        for _k in ("estimate_price", "estimate_price_net",
                   "estimate_match", "estimate_name"):
            if item.get(_k) is not None:
                analog_item[_k] = item[_k]

        # Вставляем сразу после оригинала
        try:
            idx = self.items.index(item)
            self.items.insert(idx + 1, analog_item)
        except ValueError:
            self.items.append(analog_item)

        # Сразу выставляем артикул аналога в item, чтобы _populate() показал его в c17
        if orig_article and analog_article_for_db:
            item["_analog_art"] = analog_article_for_db

        self._populate()
        self._update_stats()
        # Обновляем всю колонку аналогов (на случай других строк с тем же артикулом)
        self.after(300, self._refresh_analog_col)

    def _remove_analog_row(self, parent_item: dict):
        """Убирает аналог-строку у позиции (сброс аналога)."""
        old_analog = next(
            (i for i in self.items if i.get("is_analog_row") and i.get("_analog_parent_id") == id(parent_item)),
            None,
        )
        if old_analog:
            self.items.remove(old_analog)
        parent_item.pop("has_analog_row", None)
        self._populate()
        self._update_stats()

    def _delete_selected(self):
        """Удалить выбранную строку из списка позиций."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = self._get_item_by_iid(iid)
        if item is None:
            return
        # Сохраняем для возможного восстановления через «Сбросить»
        self._deleted_items.append(item)
        # Если удаляем оригинал — удаляем и аналог-строку под ним
        analog_sub = next(
            (i for i in self.items
             if i.get("is_analog_row") and i.get("_analog_parent_id") == id(item)),
            None,
        )
        if analog_sub:
            try:
                self.items.remove(analog_sub)
            except ValueError:
                pass
            sub_iid = analog_sub.get("_iid")
            if sub_iid and self.tree.exists(sub_iid):
                self.tree.delete(sub_iid)
        # Удаляем из данных и из дерева
        try:
            self.items.remove(item)
        except ValueError:
            pass
        if self.tree.exists(iid):
            self.tree.delete(iid)
        # Показываем кнопку «Вернуть» если не в режиме выбора
        self._update_delete_btn()
        # Обновляем счётчики статусов
        self._update_stats()

    # ── Режим выбора (галочки) ────────────────────────────────────────────
    def _toggle_select_mode(self):
        self._select_mode = not self._select_mode
        self._checked_items.clear()
        if self._select_mode:
            self.select_btn.configure(fg_color=NAVY_LIGHT, text="✖ Выйти")
            self.tree.heading("c0", text="☐  №")
        else:
            self.select_btn.configure(fg_color="#AEB6BF", text="☑ Выбрать")
            self.tree.heading("c0", text=t("col_num"))
            self.delete_checked_btn.pack_forget()
            self.reset_checked_btn.pack_forget()  # исправление: скрываем при выходе из режима
        self._populate()

    def _toggle_item_check(self, iid: str):
        item = self._get_item_by_iid(iid)
        if item is None:
            return
        is_heading = item.get("status") == "heading"
        pos = "" if is_heading else str(item.get("pos", ""))
        if id(item) in self._checked_items:
            self._checked_items.discard(id(item))
            cb = "☐"
        else:
            self._checked_items.add(id(item))
            cb = "☑"
        cur = list(self.tree.item(iid, "values"))
        cur[0] = f"{cb} {pos}" if pos else cb
        self.tree.item(iid, values=cur)
        self._update_delete_btn()

    def _select_all_toggle(self):
        all_iids = list(self.tree.get_children())
        items_list = [self._get_item_by_iid(iid) for iid in all_iids]
        pairs = [(iid, it) for iid, it in zip(all_iids, items_list) if it is not None]
        all_checked = bool(pairs) and all(id(it) in self._checked_items for _, it in pairs)
        for iid, it in pairs:
            is_heading = it.get("status") == "heading"
            pos = "" if is_heading else str(it.get("pos", ""))
            if all_checked:
                self._checked_items.discard(id(it))
                cb = "☐"
            else:
                self._checked_items.add(id(it))
                cb = "☑"
            cur = list(self.tree.item(iid, "values"))
            cur[0] = f"{cb} {pos}" if pos else cb
            self.tree.item(iid, values=cur)
        new_all = (not all_checked) and bool(pairs)
        self.tree.heading("c0", text="☑  №" if new_all else "☐  №")
        self._update_delete_btn()

    def _update_delete_btn(self):
        n = len(self._checked_items)
        n_del = len(getattr(self, "_deleted_items", []))
        if n > 0:
            _del_sfx = f" +{n_del}удал." if n_del else ""
            self.reset_checked_btn.configure(
                text=f"🔄 Сбросить ({n}){_del_sfx}")
            self.reset_checked_btn.pack(side="right", padx=(0, 4))
            self.delete_checked_btn.configure(
                text=f"🗑 Удалить ({n})")
            self.delete_checked_btn.pack(side="right", padx=(0, 0))
        elif n_del > 0:
            # Показываем кнопку возврата даже вне режима выбора
            self.reset_checked_btn.configure(
                text=f"🔄 Вернуть ({n_del})")
            self.reset_checked_btn.pack(side="right", padx=(0, 4))
            self.delete_checked_btn.pack_forget()
        else:
            self.reset_checked_btn.pack_forget()
            self.delete_checked_btn.pack_forget()

    def _reset_checked(self):
        """Сбросить выбранные позиции к исходным данным из PDF и вернуть удалённые."""
        to_reset = [i for i in self.items
                    if id(i) in self._checked_items and i.get("status") != "heading"]
        for item in to_reset:
            for key in ("best_match", "candidates", "match_method",
                        "ai_confidence", "ai_used", "ai_reason",
                        "_user_edited", "_user_const_price",
                        "_corrected_by_manager", "comment", "delivery"):
                item.pop(key, None)
            item["status"] = "not_found"
        # Восстанавливаем позиции удалённые через ппкм / Delete
        if self._deleted_items:
            self.items.extend(self._deleted_items)
            self._deleted_items.clear()
            # Перенумеруем все не-заголовочные позиции последовательно
            _new_pos = 0
            for _it in self.items:
                if _it.get("is_heading"):
                    continue
                _new_pos += 1
                _it["pos"] = str(_new_pos)
        self._checked_items.clear()
        if self._select_mode:
            self._toggle_select_mode()  # выходим из режима + перерисовываем
        else:
            self.reset_checked_btn.pack_forget()  # скрываем кнопку «Вернуть»
            self._populate()  # перерисовываем дерево
        self._update_stats()

    def _delete_checked(self):
        to_del = [i for i in self.items if id(i) in self._checked_items]
        self._deleted_items.extend(to_del)  # трекинг для восстановления через «Сбросить»
        for item in to_del:
            iid = item.get("_iid")
            try:
                self.items.remove(item)
            except ValueError:
                pass
            if iid and self.tree.exists(iid):
                self.tree.delete(iid)
        # Renumber remaining non-heading items sequentially after deletion
        _new_pos = 0
        for _it in self.items:
            if _it.get("status") == "heading":
                continue
            _new_pos += 1
            _it["pos"] = str(_new_pos)
        self._checked_items.clear()
        self._toggle_select_mode()
        self._update_stats()

    # ── Сохранение ───────────────────────────────────────────────────────────
    def _export_price(self, item: dict) -> float:
        """Цена, которая реально попадёт в лист КП.

        Повторяет правило excel_generator._prelim_of: берётся предварительная
        цена, а вычисленная «Цена КП» служит запасным вариантом.
        """
        prelim = self._prelim_price(item)
        if prelim:
            return prelim
        _s, _ss, kp, _ks = self._compute_kp(item)
        return kp

    def _confirm_export_prices(self) -> bool:
        """Показывает расхождение экранных цен с выгрузкой. False — отмена."""
        screen_sum = export_sum = 0.0
        diff_rows = []
        for it in self.items:
            if it.get("is_heading") or it.get("has_analog_row"):
                continue
            try:
                qty = float(it.get("qty", 1) or 1)
            except (TypeError, ValueError):
                qty = 1.0
            _s, _ss, kp, _ks = self._compute_kp(it)
            exp = self._export_price(it)
            screen_sum += kp * qty
            export_sum += exp * qty
            if kp and exp and abs(exp - kp) > 0.01:
                diff_rows.append((abs(exp - kp) * qty, it, kp, exp))

        delta = export_sum - screen_sum
        if not diff_rows or abs(delta) < 1.0:
            return True

        diff_rows.sort(key=lambda r: -r[0])

        def m(v):
            return f"{v:,.0f}".replace(",", " ")

        lines = []
        for _d, it, kp, exp in diff_rows[:6]:
            bm  = it.get("best_match") or {}
            nm  = (bm.get("name") or it.get("name_raw") or "")[:42]
            arrow = "↑" if exp > kp else "↓"
            lines.append(f"  • Поз.{it.get('pos', '?')}  {nm}\n"
                         f"        на экране {m(kp)} → в КП {m(exp)}  {arrow}")
        tail = f"\n  ... и ещё {len(diff_rows) - 6}" if len(diff_rows) > 6 else ""
        pct = (delta / screen_sum * 100) if screen_sum else 0.0

        msg = (
            "В лист КП записывается «Предварительная цена», а в таблице\n"
            "показана «Цена КП» — это разные значения.\n\n"
            f"Сумма КП на экране:   {m(screen_sum)} ₸\n"
            f"Сумма КП в документе: {m(export_sum)} ₸\n"
            f"Расхождение:          {m(delta)} ₸ ({pct:+.1f} %)\n\n"
            f"Расходятся {len(diff_rows)} поз., крупнейшие:\n\n"
            + "\n".join(lines) + tail
            + "\n\nСохранить с ценами из документа?"
        )
        return messagebox.askyesno("Цены в КП отличаются от экранных",
                                   msg, icon="warning")

    def _save(self):
        if not self.items:
            return

        # ── Проверка несовпадений единиц ─────────────────────────────────────
        mismatches = []
        for it in self.items:
            bm = it.get("best_match") or {}
            if not bm:
                continue
            pdf_u = (it.get("unit") or "").strip().lower()
            db_u  = (bm.get("unit") or "").strip().lower()
            if pdf_u and db_u and pdf_u != db_u and pdf_u not in ("шт", "шт."):
                mismatches.append(it)

        if mismatches:
            lines = []
            for it in mismatches[:6]:
                bm   = it.get("best_match") or {}
                pos  = it.get("pos", "?")
                nm   = (it.get("name_raw") or bm.get("name") or "")[:45]
                qty  = it.get("qty", "?")
                pu   = it.get("unit", "")
                du   = bm.get("unit", "")
                lines.append(f"  • Поз.{pos}  {nm}\n        {qty} {pu} → нужно указать в «{du}»")
            tail = f"\n  ... и ещё {len(mismatches) - 6}" if len(mismatches) > 6 else ""
            msg = (
                f"Найдено {len(mismatches)} строк с несовпадением единиц:\n\n"
                + "\n".join(lines) + tail
                + "\n\nДважды кликните по ячейке «Кол-во» чтобы исправить.\n\n"
                "Сохранить без исправления?"
            )
            if not messagebox.askyesno("Несовпадение единиц", msg, icon="warning"):
                return
        # ─────────────────────────────────────────────────────────────────────

        # ── Сумма на экране против суммы, которая уйдёт в лист КП ────────────
        if not self._confirm_export_prices():
            return

        path = filedialog.asksaveasfilename(
            title=t("preview_save"),
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")]
        )
        if not path:
            return
        try:
            for it in self.items:
                seb, seb_sum, kp, kp_sum = self._compute_kp(it)
                it["_computed_kp_price"] = kp
                it["_computed_kp_sum"]   = kp_sum
                it["_computed_seb_price"] = seb
                it["_computed_seb_sum"]   = seb_sum
                it["_prelim_price"]       = self._prelim_price(it) or None

            import tempfile
            base_tpl = ""
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xlsm")
                os.close(tmp_fd)
                if self.api.download_base_template(tmp_path):
                    base_tpl = tmp_path
                    print("[Save] Using server base template")
                else:
                    os.unlink(tmp_path)
                    print("[Save] Server base template not ready, falling back")
            except Exception as e_tpl:
                print(f"[Save] base template download: {e_tpl}")

            products = []
            if not base_tpl:
                try:
                    products = self.api.get_all_products()
                except Exception as e_db:
                    print(f"[Save] get_all_products: {e_db}")

            _incl_hdg = self._hdg_var.get() if self._hdg_var else True
            _excel_items = self.items if _incl_hdg else [
                it for it in self.items if not it.get("is_heading")
            ]
            try:
                out = generate_excel(
                    _excel_items, path,
                    constants=self.constants,
                    products=products,
                    brand_consts=self.brand_consts,
                    project_name="",
                    client_name="",
                    manager_name="",
                    base_template_path=base_tpl,
                )
            finally:
                if base_tpl and os.path.exists(base_tpl):
                    try: os.unlink(base_tpl)
                    except Exception: pass

            if messagebox.askyesno(
                t("preview_save"),
                t("preview_saved", path=out, count=len(self.items))
                + "\n\n" + t("preview_open_file"),
            ):
                self._open_file(out)
        except FileNotFoundError as e:
            messagebox.showerror(t("preview_save_error"), str(e))
        except Exception as e:
            messagebox.showerror(t("preview_save_error"), str(e))

    @staticmethod
    def _open_file(path: str):
        """Открывает файл стандартным приложением ОС."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            print(f"[open_file] {e}")
