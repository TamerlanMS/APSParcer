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
from services.excel_generator import generate_excel


# Цвета строк
C_EXACT    = "#D4EDDA"
C_MULTIPLE = "#FFF3CD"
C_NOTFOUND = "#F8D7DA"
C_EDITED   = "#CCE5FF"
C_SELECT   = "#C8DFFF"
C_AI       = "#D5F5EE"   # бирюзовый — ИИ-совпадение


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
    ("const",      "col_const"),        # 7 — Константа цена, редактируется
    ("seb",        "col_price_seb"),    # 8 — Цена себес
    ("seb_sum",    "col_sum_seb"),      # 9 — Сумма себес
    ("kp",         "col_price_kp"),     # 10 — Цена КП, редактируется
    ("kp_sum",     "col_sum_kp"),       # 11 — Сумма КП
    ("kaznisa",    "col_kaznisa_code"), # 12 — Код КазНИИСА
    ("comment",    "col_comment"),      # 13 — Комментарии (редактируется)
    ("delivery",   "col_delivery"),     # 14 — Срок поставки (редактируется)
    ("status",     "col_status"),       # 15 — Статус
    ("method",     "col_method"),       # 16 — Метод подбора
]
COL_WIDTHS    = [40, 90, 170, 230, 50, 60, 60, 90, 90, 100, 90, 100, 110, 150, 110, 100, 130]
EDITABLE_COLS = {5, 6, 7, 8, 9, 10, 11, 13, 14}  # Кол-во, Кратн., Конст.цена, Себес, ΣСеб, КП, ΣКП, Коммент., Срок


# Соответствие rate-индекс (1..8) → ключ цены из БД
RATE_FIELD = {
    1: "kaznisa",  # Сумма КазНИИСА  (kaznisa × кол-во)
    2: "kaznisa",  # Цена КазНИИСА
    3: "rrts",     # РРЦ
    4: "mrc",      # МРЦ
    5: "opt",      # Опт
    6: "rrts",     # Цена ГП  (РРЦ × коэф. ГП)
    7: "rrts",     # Сумма ГП (РРЦ × коэф. ГП × кол-во)
    8: "partner",  # Проект
}
# Типы расценки, требующие умножения базовой цены на коэффициент ГП
GP_RATE_TYPES = {6, 7}

# Подписи типов расценки (индекс 1 = RATE_LABELS[0])
RATE_LABELS = [
    "Сумма КазНИИСА",  # 1
    "Цена КазНИИСА",   # 2
    "РРЦ",             # 3
    "МРЦ",             # 4
    "Опт",             # 5
    "Цена ГП",         # 6
    "Сумма ГП",        # 7
    "Проект",          # 8
]


def _make_headers() -> List[str]:
    return [t(key) for _k, key in COLS]


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
        style.configure("Cand.Treeview.Heading", font=("Calibri", 12, "bold"),
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


class PreviewPage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api     = api
        self.app     = app
        self.items   = []
        self.constants   = {}       # raw из API
        self.brand_consts = {}      # {brand: {margin, logistics, rate, currency_rate, nds, gp}}
        self.managers    = []
        self._edit_iid   = None
        self._edit_entry = None
        self._filter_mode = "all"
        self._suppress_recalc = False
        self._rate_str_var = None

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

        self.ai_btn = ctk.CTkButton(
            top, text=t("preview_ai_rematch_btn"), font=FONT_SMALL,
            fg_color="#17A589", hover_color="#148F77", text_color="white",
            height=36, width=150, corner_radius=RADIUS_SM,
            command=self._rematch_ai_all,
        )
        self.ai_btn.grid(row=0, column=5, padx=(0, 4))

        self.save_btn = ctk.CTkButton(
            top, text=t("preview_save"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=36, width=180, corner_radius=RADIUS_SM,
            state="disabled", command=self._save
        )
        self.save_btn.grid(row=0, column=6, padx=(0, 16))

        # Легенда
        leg = ctk.CTkFrame(self, fg_color="transparent")
        leg.grid(row=1, column=0, sticky="w", padx=pad, pady=(0, 4))
        for bg, key in [
            (C_EXACT,    "preview_legend_exact"),
            (C_MULTIPLE, "preview_legend_warn"),
            (C_NOTFOUND, "preview_legend_nf"),
            (C_EDITED,   "preview_legend_edit"),
            (C_AI,       "preview_legend_ai"),
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
                        rowheight=28, font=("Calibri", 12))
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
        _HIDDEN_COLS = {12, 13, 14}  # kaznisa, comment, delivery
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

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._on_tree_single_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

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
            label=t("ctx_ai_rematch"),
            command=self._rematch_ai_selected,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(
            label=t("ctx_reset_item"),
            command=self._reset_item_selected,
        )
        self.tree.bind("<Button-3>", self._show_ctx_menu)

        # Панель «Константы по бренду»
        cf = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                          border_width=1, border_color="#E0E0E0")
        cf.grid(row=3, column=0, sticky="ew", padx=pad, pady=(0, pad))

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
            ("preview_rate_type",  "rate",          3),   # default = РРЦ (index 3)
        ]
        for col_i, (key, var_key, default) in enumerate(const_items):
            lbl = ctk.CTkLabel(cf, text=t(key), font=FONT_SMALL,
                                text_color=TEXT_SECONDARY)
            lbl.grid(row=1, column=2 + col_i * 2, padx=(8, 4), pady=(0, 10), sticky="w")
            if var_key == "rate":
                # Выпадающий список вместо числового поля
                self._rate_str_var = ctk.StringVar(value=RATE_LABELS[int(default) - 1])
                rate_dd = ctk.CTkOptionMenu(
                    cf, values=RATE_LABELS,
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
        self.items = []
        self.tree.delete(*self.tree.get_children())
        self._filter_mode = "all"
        self.search_var.set("")
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == "all" else "#AEB6BF")
        self.save_btn.configure(state="disabled")
        self.stat_lbl.configure(text="")
        self._no_data_lbl.lift()
        self.app._switch_tab(0)

    # ── Данные ───────────────────────────────────────────────────────────────
    def load_data(self, result: dict):
        # Сбрасываем фильтр и поиск чтобы не было «призраков» из предыдущего файла
        self._filter_mode = "all"
        self.search_var.set("")
        for k, btn in self.filter_btns.items():
            btn.configure(fg_color=NAVY_LIGHT if k == "all" else "#AEB6BF")

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
                    "rate":          int(b.get("rate")            or 1),
                    "currency_rate": float(b.get("currency_rate") or 1.0),
                    "nds":           float(b.get("nds")           or 1.0),
                    "gp":            float(b.get("gp")            or 1.0),
                }
            # Менеджеры из Const (B-колонка) — приходят отдельно если сервер вернёт
            self.managers = self.constants.get("managers", [])
        except Exception as e:
            print(f"[Preview] get_constants: {e}")

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
                    rate_idx = int(consts[k] or 3)
                    self.const_vars[k].set(rate_idx)
                    # Синхронизируем надпись в выпадающем списке
                    if self._rate_str_var and 1 <= rate_idx <= len(RATE_LABELS):
                        self._rate_str_var.set(RATE_LABELS[rate_idx - 1])
                else:
                    self.const_vars[k].set(consts[k])
        self._suppress_recalc = False

    def _on_brand_select(self, brand: str):
        self._load_const_fields(brand)

    def _on_rate_select(self, label: str):
        """Пользователь выбрал тип расценки из выпадающего списка."""
        try:
            idx = RATE_LABELS.index(label) + 1  # 1-based
        except ValueError:
            idx = 3
        self.const_vars["rate"].set(idx)
        # Запускаем пересчёт вручную (trace не навешан на rate)
        self._on_const_change()

    # ── Расчёт цены ──────────────────────────────────────────────────────────
    def _compute_kp(self, item: dict) -> tuple:
        """
        Возвращает (price_seb, sum_seb, price_kp, sum_kp).
        Формула из WV_template.xlsm:
            base = выбор по rate-индексу бренда из БД:
                   1=Сумма КазНИИСА, 2=Цена КазНИИСА, 3=РРЦ, 4=МРЦ,
                   5=Опт, 6=Цена ГП (РРЦ×ГП), 7=Сумма ГП, 8=Проект
                   либо ручная константа из поля G
            price_seb = base × курс × НДС × лог-ка
            price_kp  = price_seb × маржа
            суммы     = цена × Кол-во,  округление вверх.
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
                    "rate":          int(float(self.const_vars["rate"].get() or 3)),
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

        # ── Приоритет 1: пользователь задал Цена КП напрямую ────────────
        if item.get("_user_edited") and item.get("_user_price") is not None:
            price_kp  = math.ceil(float(item["_user_price"]))
            price_seb = math.ceil(price_kp / mg) if mg else price_kp
            return price_seb, price_seb * qty, price_kp, price_kp * qty

        # ── Приоритет 2: пользователь задал Цена себес напрямую ─────────
        if item.get("_user_seb_price") is not None:
            price_seb = math.ceil(float(item["_user_seb_price"]))
            price_kp  = math.ceil(price_seb * mg)
            return price_seb, price_seb * qty, price_kp, price_kp * qty

        # ── Приоритет 3: константа цена вместо базы из БД ───────────────
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
            return 0.0, 0.0, 0.0, 0.0

        price_seb = math.ceil(base * cur * nds * lo)
        price_kp  = math.ceil(price_seb * mg)
        return price_seb, price_seb * qty, price_kp, price_kp * qty

    # ── Заполнение таблицы ───────────────────────────────────────────────────
    def _populate(self, items=None):
        self.tree.delete(*self.tree.get_children())
        data = items if items is not None else self.items
        for item in data:
            self._insert_row(item)
        self._adjust_row_height()

    def _adjust_row_height(self):
        """Set rowheight to fit the tallest cell value across all visible rows."""
        max_lines = 1
        for iid in self.tree.get_children():
            for val in self.tree.item(iid, "values"):
                lines = str(val).count("\n") + 1
                if lines > max_lines:
                    max_lines = lines
        line_px  = 18   # pixels per text line at Calibri 12
        padding  = 8    # top+bottom cell padding
        new_h    = max(28, max_lines * line_px + padding)
        ttk.Style().configure("APS.Treeview", rowheight=new_h)

    @staticmethod
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
            "kaznisa":                  "КазНИИСА (код)",
        }
        if method in _MAP:
            return _MAP[method]
        if method.startswith("ai"):
            return "ИИ"
        return method

    def _insert_row(self, item: dict) -> str:
        bm           = item.get("best_match") or {}
        status       = item.get("status", "not_found")
        match_method = item.get("match_method")

        if status == "exact":
            tag, stxt = "exact",    t("status_exact")
        elif status == "multiple":
            tag, stxt = "multiple", t("status_multiple")
        elif status == "fuzzy":
            tag, stxt = "multiple", t("status_fuzzy")
        elif status == "ai_match":
            ai_conf = item.get("ai_confidence")
            conf_str = f" ({ai_conf:.0%})" if ai_conf else ""
            tag, stxt = "ai", t("status_ai_match") + conf_str
        else:
            tag, stxt = "notfound", t("status_nf")

        if item.get("_user_edited"):
            tag = "edited"

        seb, seb_sum, kp, kp_sum = self._compute_kp(item)
        qty = item.get("qty", 1)
        brand = bm.get("brand", "")
        article = (bm.get("article", "") or item.get("article_raw", "")).replace("\n", " ").strip()
        name    = (bm.get("name",    "") or item.get("name_raw", "")).replace("\n", " ").strip()
        unit    = bm.get("unit", "шт.") if bm else "шт."
        mult    = bm.get("multiplicity") or ""
        kaznisa_code = bm.get("kaznisa_code") or ""
        const_price  = item.get("_user_const_price") or ""

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

        vals = (
            item.get("pos", ""),
            brand,
            article,
            name,
            unit,
            qty,
            mult,
            const_price,
            f(seb),
            f(seb_sum),
            f(kp),
            f(kp_sum),
            kaznisa_code,
            item.get("comment", "") or "",
            item.get("delivery", "") or "",
            stxt,
            method_lbl,
        )
        iid = self.tree.insert("", "end", values=vals, tags=(tag,))
        item["_iid"] = iid
        return iid

    def _update_stats(self):
        total = len(self.items)
        exact = sum(1 for i in self.items if i.get("status") == "exact")
        warn  = sum(1 for i in self.items if i.get("status") in ("multiple","fuzzy"))
        nf    = sum(1 for i in self.items if i.get("status") == "not_found")
        # Count matched items that have no price in DB
        no_price = sum(
            1 for i in self.items
            if i.get("best_match") and i.get("status") != "not_found"
            and not any(
                i.get("best_match", {}).get(f)
                for f in ("kaznisa", "rrts", "mrc", "opt", "partner")
            )
        )
        stat_text = t("preview_stat", total=total, exact=exact, warn=warn, nf=nf)
        if no_price:
            stat_text += f"  |  ⚠ нет цены в БД: {no_price}"
        self.stat_lbl.configure(text=stat_text)

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
            bc["rate"]          = int(float(self.const_vars["rate"].get() or 3))
        except (tk.TclError, ValueError):
            return
        self._recalc_for_brand(brand)

    def _recalc_for_brand(self, brand: str):
        for item in self.items:
            bm = item.get("best_match") or {}
            if (bm.get("brand") or "").upper() != brand:
                continue
            if item.get("_user_edited"):
                continue
            iid = item.get("_iid")
            if not iid or not self.tree.exists(iid):
                continue
            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            vals = list(self.tree.item(iid, "values"))
            vals[8]  = f"{seb:.2f}"      if seb     else ""
            vals[9]  = f"{seb_sum:.2f}"  if seb_sum else ""
            vals[10] = f"{kp:.2f}"       if kp      else ""
            vals[11] = f"{kp_sum:.2f}"   if kp_sum  else ""
            self.tree.item(iid, values=vals)

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
        """Показывает сырые цены из БД в строке статуса при выборе строки."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = next((i for i in self.items if i.get("_iid") == iid), None)
        if not item:
            return
        bm = item.get("best_match") or {}
        if not bm:
            return
        # Форматируем цены из БД
        def _fmt(v):
            if v is None: return "—"
            try: return f"{float(v):,.0f}"
            except: return str(v)
        brand  = bm.get("brand") or "не задан"
        kaznisa = _fmt(bm.get("kaznisa"))
        rrts   = _fmt(bm.get("rrts"))
        mrc    = _fmt(bm.get("mrc"))
        opt    = _fmt(bm.get("opt"))
        partner = _fmt(bm.get("partner"))
        info = (
            f"БД: [{bm.get('article','')}] Бренд={brand}  "
            f"КазНИИСА={kaznisa}  РРЦ={rrts}  МРЦ={mrc}  Опт={opt}  Проект={partner}"
        )
        self.stat_lbl.configure(text=info, text_color="#E67E22")

    def _on_tree_single_click(self, event):
        """Одиночный клик по таблице: если активно inline-поле — сохраняем его."""
        if self._edit_entry and self._edit_iid:
            self._commit_edit(self._edit_entry)
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
        if item.get("status") in ("multiple", "fuzzy", "ai_match") and col_idx not in EDITABLE_COLS:
            cands = item.get("candidates", [])
            if cands:
                dlg = CandidateDialog(self, cands)
                self.wait_window(dlg)
                if dlg.selected:
                    item["best_match"] = dlg.selected
                    item["status"]     = "exact"
                    item["_user_edited"] = False
                    item["_user_price"]  = None
                    self._refresh_row(iid, item)
                    self._update_stats()
            return

        if col_idx in EDITABLE_COLS:
            self._start_edit(iid, col, col_idx, item)
        elif item.get("status") in ("multiple", "fuzzy", "ai_match"):
            # Дополнительная попытка открыть диалог кандидатов если колонка не редактируемая
            cands = item.get("candidates", [])
            if cands:
                dlg = CandidateDialog(self, cands)
                self.wait_window(dlg)
                if dlg.selected:
                    item["best_match"] = dlg.selected
                    item["status"]     = "exact"
                    item["_user_edited"] = False
                    item["_user_price"]  = None
                    self._refresh_row(iid, item)
                    self._update_stats()

    def _get_item_by_iid(self, iid: str) -> Optional[Dict]:
        for item in self.items:
            if item.get("_iid") == iid:
                return item
        return None

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
            bm.get("kaznisa_code") or "",
            item.get("comment", "") or "",
            item.get("delivery", "") or "",
            t("status_exact"),
        )
        self.tree.item(iid, values=vals, tags=("exact",))
        # Снимаем выделение, иначе цвет SELECT перекрывает зелёный тег
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

        entry = tk.Entry(self.tree, font=("Calibri", 12), relief="solid", bd=1)
        entry.insert(0, cur_val)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.bind("<Return>",   lambda e: self._commit_edit(entry))
        entry.bind("<Escape>",   lambda e: self._cancel_edit())
        entry.bind("<FocusOut>", lambda e: self._commit_edit(entry))
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
        item["best_match"] = bm  # гарантируем dict

        if col_idx == 6:              # Кратность (целое) → в best_match
            try:
                bm["multiplicity"] = int(float(raw.replace(",", "."))) if raw else None
            except ValueError:
                pass
            vals[6] = bm.get("multiplicity") or ""

        elif col_idx in (13, 14):     # Комментарий / Срок поставки — строка
            key = "comment" if col_idx == 13 else "delivery"
            item[key] = raw
            vals[col_idx] = raw

        else:                          # Числовые поля: qty(5), const(7), seb(8), seb_sum(9), kp(10), kp_sum(11)
            try:
                new_val = float(raw.replace(",", ".")) if raw else 0.0
            except ValueError:
                self._cancel_edit()
                return
            if col_idx == 5:          # Кол-во
                item["qty"] = new_val
            elif col_idx == 7:        # Константа цена → сбрасываем ручные переопределения
                item["_user_const_price"] = new_val if new_val else None
                item["_user_seb_price"]   = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == 8:        # Цена себес
                item["_user_seb_price"]   = new_val if new_val else None
                item["_user_const_price"] = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == 9:        # Сумма себес → обратный пересчёт на единицу
                qty_v = float(item.get("qty", 1) or 1)
                item["_user_seb_price"]   = (new_val / qty_v) if (new_val and qty_v) else None
                item["_user_const_price"] = None
                item["_user_edited"] = False
                item["_user_price"]  = None
            elif col_idx == 10:       # Цена КП
                item["_user_edited"] = True
                item["_user_price"]  = new_val
            elif col_idx == 11:       # Сумма КП → обратный пересчёт на единицу
                qty_v = float(item.get("qty", 1) or 1)
                item["_user_edited"] = True
                item["_user_price"]  = (new_val / qty_v) if (new_val and qty_v) else None
            # Пересчёт цен
            seb, seb_sum, kp, kp_sum = self._compute_kp(item)
            vals[5]  = item.get("qty", 1)
            vals[7]  = item.get("_user_const_price") or ""
            vals[8]  = f"{seb:.2f}"     if seb     else ""
            vals[9]  = f"{seb_sum:.2f}" if seb_sum else ""
            vals[10] = f"{kp:.2f}"      if kp      else ""
            vals[11] = f"{kp_sum:.2f}"  if kp_sum  else ""

        is_edited = bool(item.get("_user_edited") or item.get("_user_const_price") or item.get("_user_seb_price"))
        if is_edited:
            self.tree.item(iid, values=vals, tags=("edited",))
        else:
            cur_tags = self.tree.item(iid, "tags")
            self.tree.item(iid, values=vals, tags=cur_tags)
        self._cancel_edit()

    def _cancel_edit(self, event=None):
        if self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None
        self._edit_iid = None

    # ── Контекстное меню / копирование ───────────────────────────────────────
    def _show_ctx_menu(self, event):
        """Показывает контекстное меню по правому клику; выделяет строку под курсором."""
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _copy_cell(self, col_key: str):
        """Копирует значение указанной колонки выбранной строки в буфер обмена."""
        sel = self.tree.selection()
        if not sel:
            return
        # col_key — это id колонки в Treeview (совпадает с первым элементом COLS)
        col_ids = [c for c, _ in COLS]
        if col_key not in col_ids:
            return
        values = self.tree.item(sel[0], "values")
        col_idx = col_ids.index(col_key)
        value = values[col_idx] if col_idx < len(values) else ""
        self.clipboard_clear()
        self.clipboard_append(str(value))

    def _copy_row(self):
        """Копирует всю строку (артикул + код КазНИИСА) в буфер через Tab."""
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
    def _rematch_ai_all(self):
        """Переподобрать все жёлтые (multiple/fuzzy) и красные (not_found) строки через ИИ."""
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
        """Переподобрать выбранную строку через ИИ (контекстное меню)."""
        sel = self.tree.selection()
        if not sel:
            return
        item = self._get_item_by_iid(sel[0])
        if item is None:
            return
        self._run_rematch([item])

    def _run_rematch(self, targets: list):
        """Запускает AI re-match в фоновом потоке и обновляет строки по результату."""
        self.ai_btn.configure(state="disabled", text="⏳ ИИ...")

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
        """Применяет результаты AI re-match к items и перерисовывает строки."""
        for item, new_data in zip(targets, results):
            for key in ("status", "best_match", "candidates",
                        "match_method", "ai_confidence", "ai_used", "ai_reason"):
                if key in new_data:
                    item[key] = new_data[key]
            iid = item.get("_iid")
            if iid and self.tree.exists(iid):
                self.tree.delete(iid)
                self._insert_row(item)
        self._update_stats()
        self.ai_btn.configure(state="normal", text=t("preview_ai_rematch_btn"))

    def _rematch_error(self, error: str):
        self.ai_btn.configure(state="normal", text=t("preview_ai_rematch_btn"))
        messagebox.showerror("ИИ-переподбор", f"Ошибка:\n{error}")

    def _reset_item_selected(self):
        """Сбрасывает выбранную позицию к исходным данным из спецификации."""
        sel = self.tree.selection()
        if not sel:
            return
        item = self._get_item_by_iid(sel[0])
        if item is None:
            return
        # Очищаем результаты подбора
        for key in ("best_match", "candidates", "match_method",
                    "ai_confidence", "ai_used", "ai_reason",
                    "_user_edited", "_user_const_price",
                    "comment", "delivery"):
            item.pop(key, None)
        item["status"] = "not_found"
        # Перерисовываем строку
        iid = item.get("_iid")
        if iid and self.tree.exists(iid):
            self.tree.delete(iid)
        self._insert_row(item)
        self._update_stats()

    # ── Сохранение ───────────────────────────────────────────────────────────
    def _save(self):
        if not self.items:
            return
        managers = self.managers or []
        dlg = SaveKPDialog(self, managers)
        self.wait_window(dlg)
        if not dlg.result:
            return
        meta = dlg.result

        path = filedialog.asksaveasfilename(
            title=t("preview_save"),
            defaultextension=".xlsm",
            filetypes=[("Excel с макросами", "*.xlsm")]
        )
        if not path:
            return
        try:
            # Вычисляем цены КП для каждой позиции
            for it in self.items:
                seb, seb_sum, kp, kp_sum = self._compute_kp(it)
                it["_computed_kp_price"] = kp
                it["_computed_kp_sum"]   = kp_sum

            # Пробуем скачать готовый шаблон (БД + Const) с сервера
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
                if 'tmp_path' in dir() and os.path.exists(tmp_path):
                    try: os.unlink(tmp_path)
                    except Exception: pass

            # Если шаблон не скачан — грузим продукты сами (старый путь)
            products = []
            if not base_tpl:
                try:
                    products = self.api.get_all_products()
                except Exception as e_db:
                    print(f"[Save] get_all_products: {e_db}")

            try:
                out = generate_excel(
                    self.items, path,
                    constants=self.constants,
                    products=products,
                    brand_consts=self.brand_consts,
                    project_name=meta.get("project", ""),
                    client_name=meta.get("client", ""),
                    manager_name=meta.get("manager", ""),
                    base_template_path=base_tpl,
                )
            finally:
                # Удаляем временный файл шаблона в любом случае
                if base_tpl and os.path.exists(base_tpl):
                    try: os.unlink(base_tpl)
                    except Exception: pass

            # Предлагаем открыть файл
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
        """ÐÑÐºÑÑÐ²Ð°ÐµÑ ÑÐ°Ð¹Ð» ÑÑÐ°Ð½Ð´Ð°ÑÑÐ½ÑÐ¼ Ð¿ÑÐ¸Ð»Ð¾Ð¶ÐµÐ½Ð¸ÐµÐ¼ ÐÐ¡."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            print(f"[open_file] {e}")
