# -*- coding: utf-8 -*-
"""
Диалог «Подобрать аналог».
Светлая тема — хорошая читаемость текста.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import customtkinter as ctk

PROVIDERS = [
    ("dkc",    "ДКС"),
    ("ekf",    "EKF"),
    ("iek",    "IEK"),
    ("chint",  "CHINT"),
    ("bonpet", "BonPet"),
]

# ── Палитра (светлая) ──────────────────────────────────────────────────────────
_BG_WINDOW   = "#F0F2F5"   # фон окна
_BG_HEADER   = "#1E3A5F"   # шапка — тёмно-синяя
_BG_ARTBAR   = "#FFFFFF"   # строка артикула — белая
_BG_RESULTS  = "#FFFFFF"   # область результатов
_ROW_ODD     = "#F7F9FC"   # нечётная строка
_ROW_EVEN    = "#FFFFFF"   # чётная строка
_ROW_HOVER   = "#EBF3FF"   # hover

_TXT_HEADER  = "#FFFFFF"   # текст шапки
_TXT_LABEL   = "#374151"   # обычный текст
_TXT_SUB     = "#6B7280"   # второстепенный текст
_TXT_ART     = "#111827"   # артикул в результатах
_TXT_NAME    = "#374151"   # наименование
_TXT_MATCH   = "#166534"   # «✓ В базе»
_TXT_NOMATCH = "#9CA3AF"   # «Нет в базе»
_TXT_ERR     = "#991B1B"   # ошибка

_BTN_DEFAULT = "#374151"   # кнопка провайдера — неактивная
_BTN_ACTIVE  = "#1D4ED8"   # активная (выбранная)
_BTN_HOVER   = "#4B5563"
_BTN_MATCH   = "#166534"   # кнопка «Выбрать» / «Применить»
_BTN_MATCH_H = "#14532D"
_BTN_CLOSE   = "#6B7280"
_BTN_CLOSE_H = "#4B5563"
_BTN_CLEAR   = "#9CA3AF"
_BTN_CLEAR_H = "#EF4444"

_BORDER      = "#D1D5DB"   # рамки
_ENTRY_BG    = "#FFFFFF"
_ENTRY_BOR   = "#9CA3AF"
_SEG_TAG     = "#DBEAFE"   # бэдж сегмента
_SEG_TXT     = "#1E40AF"


class AnalogDialog(ctk.CTkToplevel):
    """
    Параметры
    ---------
    parent       : родительское окно
    article      : оригинальный артикул (может быть пустым)
    api_service  : экземпляр ApiService
    on_apply     : callback(db_match: dict)
    segment      : сегмент внутренней БД
    """

    def __init__(
        self,
        parent,
        article: str,
        api_service,
        on_apply: Callable[[dict], None],
        segment: str = "ss",
    ):
        super().__init__(parent)
        self.title("Подбор аналога")
        self.geometry("720x620")
        self.resizable(False, False)
        self.configure(fg_color=_BG_WINDOW)
        self.grab_set()
        self.focus_force()

        self._article_init = article.strip()
        self._segment      = segment or "ss"
        self._api          = api_service
        self._on_apply     = on_apply
        self._results: list[dict] = []
        self._selected_idx: Optional[int] = None

        self._build()
        self.after(100, self._center)

    # ──────────────────────────────────────────────────────────────────────────

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = self.winfo_screenwidth()  // 2 - w // 2
        y = self.winfo_screenheight() // 2 - h // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ──────────────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=_BG_HEADER, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr,
            text="🔍  Подбор аналога",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=_TXT_HEADER,
        ).pack(side="left", padx=18, pady=0)

        # ── Строка артикула ───────────────────────────────────────────────────
        art_frame = ctk.CTkFrame(
            self, fg_color=_BG_ARTBAR, corner_radius=0,
            border_width=1, border_color=_BORDER, height=54,
        )
        art_frame.pack(fill="x")
        art_frame.pack_propagate(False)

        ctk.CTkLabel(
            art_frame,
            text="Артикул:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_TXT_LABEL,
            width=78,
            anchor="e",
        ).pack(side="left", padx=(16, 6))

        self._article_var = ctk.StringVar(value=self._article_init)
        self._article_entry = ctk.CTkEntry(
            art_frame,
            textvariable=self._article_var,
            font=ctk.CTkFont(size=14, weight="bold"),
            width=350,
            height=34,
            placeholder_text="Введите артикул…",
            fg_color=_ENTRY_BG,
            border_color=_ENTRY_BOR,
            text_color=_TXT_ART,
        )
        self._article_entry.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            art_frame,
            text="✕",
            width=30, height=30,
            fg_color=_BTN_CLEAR,
            hover_color=_BTN_CLEAR_H,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12),
            corner_radius=6,
            command=lambda: self._article_var.set(""),
        ).pack(side="left", padx=(0, 12))

        # Бэдж сегмента
        seg_lbl = ctk.CTkLabel(
            art_frame,
            text=f"  {self._segment.upper()}  ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_SEG_TXT,
            fg_color=_SEG_TAG,
            corner_radius=4,
        )
        seg_lbl.pack(side="left")

        # ── Кнопки провайдеров ────────────────────────────────────────────────
        prov_outer = ctk.CTkFrame(self, fg_color=_BG_WINDOW, corner_radius=0)
        prov_outer.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            prov_outer,
            text="Провайдер:",
            font=ctk.CTkFont(size=12),
            text_color=_TXT_SUB,
        ).pack(anchor="w", pady=(0, 6))

        btn_row = ctk.CTkFrame(prov_outer, fg_color="transparent")
        btn_row.pack(fill="x")
        self._prov_btns: dict[str, ctk.CTkButton] = {}
        for key, label in PROVIDERS:
            btn = ctk.CTkButton(
                btn_row,
                text=label,
                width=118, height=34,
                fg_color=_BTN_DEFAULT,
                hover_color=_BTN_HOVER,
                text_color="#FFFFFF",
                font=ctk.CTkFont(size=13, weight="bold"),
                corner_radius=6,
                command=lambda k=key: self._search(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self._prov_btns[key] = btn

        # ── Статус ────────────────────────────────────────────────────────────
        self._status_var = ctk.StringVar(value="")
        self._status_lbl = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=12),
            text_color=_TXT_SUB,
            anchor="w",
        )
        self._status_lbl.pack(fill="x", padx=16, pady=(0, 4))

        # ── Прогресс (скрыт изначально) ───────────────────────────────────────
        self._progress = ctk.CTkProgressBar(
            self, mode="indeterminate",
            fg_color="#E5E7EB", progress_color=_BTN_ACTIVE,
        )

        # ── Область результатов ───────────────────────────────────────────────
        results_outer = ctk.CTkFrame(
            self, fg_color=_BG_RESULTS, corner_radius=8,
            border_width=1, border_color=_BORDER,
        )
        results_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # Заголовок таблицы
        th = ctk.CTkFrame(results_outer, fg_color="#E5E7EB", corner_radius=0, height=30)
        th.pack(fill="x")
        th.pack_propagate(False)
        for col, w in [("Артикул", 160), ("Наименование", 340), ("", 100)]:
            ctk.CTkLabel(
                th, text=col,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_TXT_LABEL,
                width=w, anchor="w",
            ).pack(side="left", padx=(10, 0))

        self._scroll = ctk.CTkScrollableFrame(
            results_outer, fg_color="transparent", corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True, padx=0, pady=0)

        self._empty_lbl = ctk.CTkLabel(
            self._scroll,
            text="Введите артикул и выберите провайдера для поиска",
            text_color=_TXT_NOMATCH,
            font=ctk.CTkFont(size=13),
        )
        self._empty_lbl.pack(pady=40)

        # ── Подвал ────────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(
            self, fg_color="#F9FAFB", corner_radius=0,
            border_width=1, border_color=_BORDER, height=54,
        )
        footer.pack(fill="x")
        footer.pack_propagate(False)

        self._apply_btn = ctk.CTkButton(
            footer,
            text="✓ Применить",
            width=140, height=36,
            fg_color=_BTN_MATCH,
            hover_color=_BTN_MATCH_H,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=6,
            state="disabled",
            command=self._apply,
        )
        self._apply_btn.pack(side="right", padx=(0, 14), pady=9)

        ctk.CTkButton(
            footer,
            text="Закрыть",
            width=100, height=36,
            fg_color=_BTN_CLOSE,
            hover_color=_BTN_CLOSE_H,
            text_color="#FFFFFF",
            corner_radius=6,
            command=self.destroy,
        ).pack(side="right", padx=(0, 8), pady=9)

        self._cached_lbl = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=_TXT_SUB,
        )
        self._cached_lbl.pack(side="left", padx=14, pady=9)

        if not self._article_init:
            self.after(200, self._article_entry.focus_set)

    # ──────────────────────────────────────────────────────────────────────────

    def _get_article(self) -> str:
        return self._article_var.get().strip()

    def _search(self, provider_key: str):
        article = self._get_article()
        if not article:
            self._status_var.set("⚠  Введите артикул для поиска")
            self._status_lbl.configure(text_color=_TXT_ERR)
            self._article_entry.focus_set()
            return

        self._selected_idx = None
        self._apply_btn.configure(state="disabled")
        self._cached_lbl.configure(text="")
        self._status_lbl.configure(text_color=_TXT_SUB)
        for k, btn in self._prov_btns.items():
            btn.configure(fg_color=_BTN_ACTIVE if k == provider_key else _BTN_DEFAULT)
        self._clear_results()
        prov_name = dict(PROVIDERS).get(provider_key, provider_key)
        self._status_var.set(f"Запрос к {prov_name} по «{article}»…")
        self._progress.pack(fill="x", padx=14, pady=(0, 4))
        self._progress.start()

        def _run():
            try:
                data = self._api.search_analogs(
                    article, provider_key, segment=self._segment)
                self.after(0, lambda: self._show_results(data, provider_key, article))
            except Exception as e:
                self.after(0, lambda err=e: self._show_error(str(err)))

        threading.Thread(target=_run, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────────

    def _show_results(self, data: dict, provider_key: str, searched_article: str):
        self._progress.stop()
        self._progress.pack_forget()
        self._clear_results()
        self._results = []

        analogs   = data.get("analogs", [])
        cached    = data.get("cached", False)
        prov_err  = data.get("provider_error")
        prov_name = dict(PROVIDERS).get(provider_key, provider_key)

        if cached:
            self._cached_lbl.configure(text="📦 Из кэша")

        if prov_err and not analogs:
            self._status_var.set(f"⚠  {prov_name}: {prov_err}")
            self._status_lbl.configure(text_color=_TXT_ERR)
            ctk.CTkLabel(
                self._scroll,
                text=prov_err,
                text_color=_TXT_ERR,
                font=ctk.CTkFont(size=12),
                wraplength=640,
                justify="left",
            ).pack(pady=20, padx=16, anchor="w")
            return

        if not analogs:
            self._status_lbl.configure(text_color=_TXT_SUB)
            self._status_var.set(
                f"{prov_name}: аналогов для «{searched_article}» не найдено"
            )
            ctk.CTkLabel(
                self._scroll,
                text="Аналоги не найдены",
                text_color=_TXT_NOMATCH,
                font=ctk.CTkFont(size=13),
            ).pack(pady=40)
            return

        n_match = sum(1 for a in analogs if a.get("db_match"))
        self._status_lbl.configure(text_color=_TXT_LABEL)
        self._status_var.set(
            f"{prov_name}: найдено {len(analogs)}  |  В базе: {n_match}"
        )

        self._results = analogs
        for idx, analog in enumerate(analogs):
            self._build_result_row(idx, analog)

    def _show_error(self, msg: str):
        self._progress.stop()
        self._progress.pack_forget()
        self._status_var.set(f"Ошибка запроса")
        self._status_lbl.configure(text_color=_TXT_ERR)
        ctk.CTkLabel(
            self._scroll,
            text=msg,
            text_color=_TXT_ERR,
            font=ctk.CTkFont(size=12),
            wraplength=640,
            justify="left",
        ).pack(pady=20, padx=16, anchor="w")

    # ──────────────────────────────────────────────────────────────────────────

    def _build_result_row(self, idx: int, analog: dict):
        art   = analog.get("analog_article", "")
        name  = analog.get("analog_name") or ""
        match = analog.get("db_match")

        row = ctk.CTkFrame(
            self._scroll,
            fg_color=_ROW_ODD if idx % 2 == 0 else _ROW_EVEN,
            corner_radius=0,
            border_width=0,
        )
        row.pack(fill="x", padx=0, pady=0)

        # Артикул
        art_cell = ctk.CTkFrame(row, fg_color="transparent", width=160)
        art_cell.pack(side="left", padx=(10, 0), pady=6)
        art_cell.pack_propagate(False)
        ctk.CTkLabel(
            art_cell,
            text=art,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_BTN_ACTIVE,
            anchor="w",
            wraplength=148,
            justify="left",
        ).pack(anchor="w")

        # Наименование + статус в базе
        name_cell = ctk.CTkFrame(row, fg_color="transparent")
        name_cell.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)

        if name:
            ctk.CTkLabel(
                name_cell,
                text=name[:100] + ("…" if len(name) > 100 else ""),
                font=ctk.CTkFont(size=12),
                text_color=_TXT_NAME,
                anchor="w",
                wraplength=320,
                justify="left",
            ).pack(anchor="w")

        if match:
            db_name = match.get("name", "")
            ctk.CTkLabel(
                name_cell,
                text=f"✓ В базе: {db_name[:55]}{'…' if len(db_name) > 55 else ''}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_TXT_MATCH,
                anchor="w",
            ).pack(anchor="w")
        else:
            ctk.CTkLabel(
                name_cell,
                text="Нет в базе",
                font=ctk.CTkFont(size=11),
                text_color=_TXT_NOMATCH,
                anchor="w",
            ).pack(anchor="w")

        # Кнопка выбора
        right = ctk.CTkFrame(row, fg_color="transparent", width=96)
        right.pack(side="right", padx=(0, 10), pady=6)
        right.pack_propagate(False)

        if match:
            sel_btn = ctk.CTkButton(
                right,
                text="Выбрать",
                width=86, height=28,
                fg_color=_BTN_MATCH,
                hover_color=_BTN_MATCH_H,
                text_color="#FFFFFF",
                font=ctk.CTkFont(size=12),
                corner_radius=5,
                command=lambda i=idx: self._select_row(i),
            )
            sel_btn.pack()
            analog["_sel_btn"] = sel_btn

        # Разделитель
        sep = ctk.CTkFrame(self._scroll, fg_color=_BORDER, height=1)
        sep.pack(fill="x")

    # ──────────────────────────────────────────────────────────────────────────

    def _select_row(self, idx: int):
        if self._selected_idx is not None:
            prev = self._results[self._selected_idx]
            btn  = prev.get("_sel_btn")
            if btn:
                btn.configure(fg_color=_BTN_MATCH, text="Выбрать")

        self._selected_idx = idx
        cur = self._results[idx]
        btn = cur.get("_sel_btn")
        if btn:
            btn.configure(fg_color=_BTN_ACTIVE, text="✓ Выбрано")

        self._apply_btn.configure(state="normal")

    # ──────────────────────────────────────────────────────────────────────────

    def _apply(self):
        if self._selected_idx is None:
            return
        analog   = self._results[self._selected_idx]
        db_match = analog.get("db_match")
        if db_match:
            self._on_apply(db_match)
            self.destroy()

    def _clear_results(self):
        for w in self._scroll.winfo_children():
            w.destroy()
