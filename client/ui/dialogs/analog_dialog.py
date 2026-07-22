# -*- coding: utf-8 -*-
"""
Диалог «Подобрать аналог».

Открывается из контекстного меню списка предпросмотра.
Показывает:
  - редактируемое поле артикула (можно ввести вручную)
  - 5 кнопок провайдеров (ДКС / EKF / IEK / CHINT / BonPet)
  - индикатор загрузки
  - список найденных аналогов с отметкой «✓ В базе»
  - кнопку «Применить» для позиций у которых есть совпадение в БД
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

_CLR_DEFAULT  = "#2B2D42"
_CLR_ACTIVE   = "#1F6AA5"
_CLR_HOVER    = "#3B3D52"
_CLR_MATCH    = "#1B7A3A"
_CLR_NOMATCH  = "#6B3A1B"


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
        self.geometry("700x600")
        self.resizable(False, False)
        self.grab_set()
        self.focus_force()

        self._article_init = article.strip()
        self._segment      = segment or "ss"
        self._api          = api_service
        self._on_apply     = on_apply
        self._results: list[dict] = []
        self._selected_idx: Optional[int] = None
        self._active_provider: Optional[str] = None

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
        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="#1A1A2E", corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text="🔍 Подбор аналога",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left", padx=16, pady=10)

        # ── Article input row ─────────────────────────────────────────────────
        art_frame = ctk.CTkFrame(self, fg_color="#1E1E30", corner_radius=0)
        art_frame.pack(fill="x")

        ctk.CTkLabel(
            art_frame,
            text="Артикул:",
            font=ctk.CTkFont(size=13),
            text_color="#AAB4C8",
            width=80,
            anchor="e",
        ).pack(side="left", padx=(16, 6), pady=10)

        self._article_var = ctk.StringVar(value=self._article_init)
        self._article_entry = ctk.CTkEntry(
            art_frame,
            textvariable=self._article_var,
            font=ctk.CTkFont(size=14, weight="bold"),
            width=340,
            height=34,
            placeholder_text="Введите артикул для поиска…",
            fg_color="#252540",
            border_color="#3A3A5A",
        )
        self._article_entry.pack(side="left", padx=(0, 8), pady=10)

        ctk.CTkButton(
            art_frame,
            text="✕",
            width=32,
            height=34,
            fg_color="#3A3A4A",
            hover_color="#5A3A3A",
            font=ctk.CTkFont(size=12),
            command=lambda: self._article_var.set(""),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkLabel(
            art_frame,
            text=f"сегмент: {self._segment}",
            font=ctk.CTkFont(size=11),
            text_color="#555577",
        ).pack(side="left", padx=(10, 16))

        # ── Provider buttons ──────────────────────────────────────────────────
        prov_frame = ctk.CTkFrame(self, fg_color="transparent")
        prov_frame.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            prov_frame, text="Выберите провайдера:",
            font=ctk.CTkFont(size=12), text_color="#AAB4C8",
        ).pack(anchor="w", padx=2, pady=(0, 6))

        btn_row = ctk.CTkFrame(prov_frame, fg_color="transparent")
        btn_row.pack(fill="x")
        self._prov_btns: dict[str, ctk.CTkButton] = {}
        for key, label in PROVIDERS:
            btn = ctk.CTkButton(
                btn_row,
                text=label,
                width=120,
                height=36,
                fg_color=_CLR_DEFAULT,
                hover_color=_CLR_HOVER,
                corner_radius=8,
                command=lambda k=key: self._search(k),
            )
            btn.pack(side="left", padx=4)
            self._prov_btns[key] = btn

        # ── Status label ──────────────────────────────────────────────────────
        self._status_var = ctk.StringVar(value="")
        self._status_lbl = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=12),
            text_color="#AAB4C8",
            anchor="w",
        )
        self._status_lbl.pack(fill="x", padx=16, pady=(4, 0))

        # ── Progress bar (hidden initially) ──────────────────────────────────
        self._progress = ctk.CTkProgressBar(self, mode="indeterminate")

        # ── Results scrollable frame ──────────────────────────────────────────
        results_outer = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=10)
        results_outer.pack(fill="both", expand=True, padx=14, pady=8)

        ctk.CTkLabel(
            results_outer,
            text="Результаты:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#AAB4C8",
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self._scroll = ctk.CTkScrollableFrame(
            results_outer, fg_color="transparent", corner_radius=0
        )
        self._scroll.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        self._empty_lbl = ctk.CTkLabel(
            self._scroll,
            text="Введите артикул и нажмите кнопку провайдера для поиска",
            text_color="#666677",
            font=ctk.CTkFont(size=12),
        )
        self._empty_lbl.pack(pady=40)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 12))

        self._apply_btn = ctk.CTkButton(
            footer,
            text="✓ Применить",
            width=140,
            height=36,
            fg_color=_CLR_MATCH,
            hover_color="#156130",
            state="disabled",
            command=self._apply,
        )
        self._apply_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            footer,
            text="Закрыть",
            width=100,
            height=36,
            fg_color="#3A3A4A",
            hover_color="#4A4A5A",
            command=self.destroy,
        ).pack(side="right", padx=4)

        self._cached_lbl = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#666677",
        )
        self._cached_lbl.pack(side="left", padx=4)

        # Фокус на поле артикула если оно пустое
        if not self._article_init:
            self.after(200, self._article_entry.focus_set)

    # ──────────────────────────────────────────────────────────────────────────

    def _get_article(self) -> str:
        return self._article_var.get().strip()

    def _search(self, provider_key: str):
        article = self._get_article()
        if not article:
            self._status_var.set("⚠ Введите артикул для поиска")
            self._article_entry.focus_set()
            return

        self._active_provider = provider_key
        self._selected_idx    = None
        self._apply_btn.configure(state="disabled")
        self._cached_lbl.configure(text="")
        for k, btn in self._prov_btns.items():
            btn.configure(
                fg_color=_CLR_ACTIVE if k == provider_key else _CLR_DEFAULT
            )
        self._clear_results()
        prov_name = dict(PROVIDERS).get(provider_key, provider_key)
        self._status_var.set(f"Запрос к {prov_name} по «{article}»…")
        self._progress.pack(fill="x", padx=14, pady=2)
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
            self._cached_lbl.configure(text="📦 Из кэша (≤30 дней)")

        if prov_err and not analogs:
            self._status_var.set(f"⚠ {prov_name}: {prov_err}")
            ctk.CTkLabel(
                self._scroll,
                text=prov_err,
                text_color="#E07050",
                font=ctk.CTkFont(size=12),
                wraplength=620,
            ).pack(pady=20)
            return

        if not analogs:
            self._status_var.set(
                f"{prov_name}: аналогов для «{searched_article}» не найдено"
            )
            ctk.CTkLabel(
                self._scroll,
                text="Аналоги не найдены для данного артикула",
                text_color="#666677",
                font=ctk.CTkFont(size=12),
            ).pack(pady=40)
            return

        n_match = sum(1 for a in analogs if a.get("db_match"))
        self._status_var.set(
            f"{prov_name}: найдено {len(analogs)} аналог(а). "
            f"В базе: {n_match}"
        )

        self._results = analogs
        for idx, analog in enumerate(analogs):
            self._build_result_row(idx, analog)

    def _show_error(self, msg: str):
        self._progress.stop()
        self._progress.pack_forget()
        self._status_var.set(f"Ошибка: {msg}")
        ctk.CTkLabel(
            self._scroll,
            text=f"Ошибка запроса:\n{msg}",
            text_color="#E07050",
            font=ctk.CTkFont(size=12),
            wraplength=620,
        ).pack(pady=20)

    # ──────────────────────────────────────────────────────────────────────────

    def _build_result_row(self, idx: int, analog: dict):
        art   = analog.get("analog_article", "")
        name  = analog.get("analog_name") or ""
        match = analog.get("db_match")

        row = ctk.CTkFrame(
            self._scroll,
            fg_color="#252535" if idx % 2 == 0 else "#1E1E2E",
            corner_radius=6,
        )
        row.pack(fill="x", padx=4, pady=2)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        ctk.CTkLabel(
            left,
            text=art,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
            text_color="#E0E0F0",
        ).pack(anchor="w")

        if name:
            ctk.CTkLabel(
                left,
                text=name[:90] + ("…" if len(name) > 90 else ""),
                font=ctk.CTkFont(size=11),
                text_color="#AAB4C8",
                anchor="w",
            ).pack(anchor="w")

        if match:
            db_info = f"✓ В базе: {match.get('name', '')[:60]}"
            ctk.CTkLabel(
                left,
                text=db_info,
                font=ctk.CTkFont(size=11),
                text_color="#4CAF7D",
                anchor="w",
            ).pack(anchor="w")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right", padx=10, pady=6)

        if match:
            sel_btn = ctk.CTkButton(
                right,
                text="Выбрать",
                width=80,
                height=28,
                fg_color=_CLR_MATCH,
                hover_color="#156130",
                command=lambda i=idx: self._select_row(i),
            )
            sel_btn.pack()
            analog["_sel_btn"] = sel_btn
        else:
            ctk.CTkLabel(
                right,
                text="Нет в базе",
                font=ctk.CTkFont(size=11),
                text_color="#6B6B7B",
            ).pack()

    # ──────────────────────────────────────────────────────────────────────────

    def _select_row(self, idx: int):
        if self._selected_idx is not None:
            prev = self._results[self._selected_idx]
            btn  = prev.get("_sel_btn")
            if btn:
                btn.configure(fg_color=_CLR_MATCH, text="Выбрать")

        self._selected_idx = idx
        cur = self._results[idx]
        btn = cur.get("_sel_btn")
        if btn:
            btn.configure(fg_color=_CLR_ACTIVE, text="✓ Выбрано")

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
        for widget in self._scroll.winfo_children():
            widget.destroy()
