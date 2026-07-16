# -*- coding: utf-8 -*-
"""
Фаза 4 — Аналитика.
Дашборд KPI менеджеров и общей статистики КП.
Доступен: administrator / superadmin / director.
"""
import threading
import customtkinter as ctk
from tkinter import ttk

from assets.theme import *
from locales.strings import t


# ── Цвета карточек KPI ────────────────────────────────────────────────────────
CARD_COLORS = [
    ("#2C3E50", "#ECF0F1"),   # тёмно-синий — кол-во КП
    ("#1A6B3A", "#E9F7EF"),   # зелёный    — позиции
    ("#145A8C", "#EBF5FB"),   # синий      — менеджеры
    ("#7B241C", "#FDEDEC"),   # красный    — ошибки
]

PERIOD_OPTIONS = [
    ("7 дн.",  7),
    ("30 дн.", 30),
    ("90 дн.", 90),
]


class _KpiCard(ctk.CTkFrame):
    """Одна сводная карточка: иконка + число + подпись."""

    def __init__(self, parent, icon: str, label: str, accent: str, bg: str, **kw):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                         border_width=2, border_color=accent, **kw)

        top = ctk.CTkFrame(self, fg_color=accent, corner_radius=RADIUS_SM,
                           width=42, height=42)
        top.pack(anchor="w", padx=14, pady=(14, 6))
        top.pack_propagate(False)
        ctk.CTkLabel(top, text=icon, font=("Segoe UI Emoji", 18),
                     text_color="white").place(relx=0.5, rely=0.5, anchor="center")

        self._value_lbl = ctk.CTkLabel(self, text="—",
                                        font=("Calibri", 22, "bold"),
                                        text_color=accent)
        self._value_lbl.pack(anchor="w", padx=14)

        ctk.CTkLabel(self, text=label, font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).pack(anchor="w", padx=14, pady=(2, 12))

    def set(self, value):
        self._value_lbl.configure(text=str(value))


class AnalyticsPage(ctk.CTkFrame):
    """Страница аналитики (Фаза 4 — пункты 1+2)."""

    def __init__(self, parent, api, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api = api
        self.app = app
        self._period = 30          # дней по умолчанию
        self._loading = False
        self._build()

    # ── Построение интерфейса ─────────────────────────────────────────────────

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=NAVY_DARK, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="📈  Аналитика",
            font=FONT_HEADING, text_color="white",
        ).grid(row=0, column=0, padx=20, pady=14, sticky="w")

        # Выбор периода
        period_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        period_frame.grid(row=0, column=2, padx=20, pady=10, sticky="e")

        ctk.CTkLabel(period_frame, text="Период:", font=FONT_SMALL,
                     text_color=TEXT_NAV).pack(side="left", padx=(0, 6))

        period_labels = [p[0] for p in PERIOD_OPTIONS]
        self._period_var = ctk.StringVar(value=period_labels[1])  # "30 дн."
        self._period_seg = ctk.CTkSegmentedButton(
            period_frame,
            values=period_labels,
            variable=self._period_var,
            font=FONT_SMALL,
            selected_color=BLUE_MID,
            selected_hover_color=NAVY_DARK,
            unselected_color="#1E3D6B",
            unselected_hover_color=NAVY_DARK,
            text_color="white",
            text_color_disabled="#8899AA",
            height=28,
            command=self._on_period_change,
        )
        self._period_seg.pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            period_frame, text="↻", font=("Calibri", 15, "bold"),
            fg_color="#1E3D6B", hover_color=BLUE_MID,
            text_color="white", width=32, height=28,
            corner_radius=RADIUS_SM, command=self.load,
        )
        self._refresh_btn.pack(side="left", padx=(8, 0))

        # ── Контент ────────────────────────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_MAIN, corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        self._scroll = scroll

        # Статус-лейбл
        self._status_lbl = ctk.CTkLabel(
            scroll, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY,
        )
        self._status_lbl.grid(row=0, column=0, pady=(10, 0))

        # ── Карточки KPI ───────────────────────────────────────────────────────
        cards_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cards_frame.grid(row=1, column=0, sticky="ew", padx=PAD_MD, pady=(12, 0))
        for i in range(4):
            cards_frame.grid_columnconfigure(i, weight=1, uniform="card")

        icons  = ["📋", "📦", "👤", "⚠️"]
        labels = ["КП за период", "Позиций обработано", "Активных менеджеров", "Ошибок"]
        accents = [c[0] for c in CARD_COLORS]

        self._cards: list[_KpiCard] = []
        for i, (icon, label, accent) in enumerate(zip(icons, labels, accents)):
            card = _KpiCard(cards_frame, icon=icon, label=label,
                            accent=accent, bg=BG_CARD)
            card.grid(row=0, column=i, sticky="nsew", padx=6, pady=6)
            self._cards.append(card)

        # ── Avg items mini-label ───────────────────────────────────────────────
        self._avg_lbl = ctk.CTkLabel(
            scroll, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY,
        )
        self._avg_lbl.grid(row=2, column=0, sticky="w", padx=PAD_MD + 6, pady=(4, 0))

        # ── KPI таблица менеджеров ─────────────────────────────────────────────
        tbl_header = ctk.CTkFrame(scroll, fg_color="transparent")
        tbl_header.grid(row=3, column=0, sticky="ew", padx=PAD_MD, pady=(16, 0))
        ctk.CTkLabel(tbl_header, text="KPI менеджеров",
                     font=FONT_HEADING, text_color=NAVY_DARK).pack(side="left")

        tbl_wrap = ctk.CTkFrame(scroll, fg_color=BG_CARD,
                                corner_radius=RADIUS_MD, border_width=1,
                                border_color="#DDE2E8")
        tbl_wrap.grid(row=4, column=0, sticky="nsew", padx=PAD_MD, pady=(8, PAD_MD))
        tbl_wrap.grid_columnconfigure(0, weight=1)
        tbl_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Analytics.Treeview",
                        background=BG_CARD,
                        foreground="#2C3E50",
                        rowheight=34,
                        fieldbackground=BG_CARD,
                        bordercolor="#DDE2E8",
                        relief="flat",
                        font=("Calibri", 12))
        style.configure("Analytics.Treeview.Heading",
                        background=NAVY_DARK,
                        foreground="white",
                        font=("Calibri", 11, "bold"),
                        relief="flat")
        style.map("Analytics.Treeview",
                  background=[("selected", BLUE_MID)],
                  foreground=[("selected", "white")])
        style.map("Analytics.Treeview.Heading", relief=[("active", "flat")])

        cols = ("full_name", "total_kp", "total_items", "avg_items", "last_activity")
        self._tree = ttk.Treeview(tbl_wrap, columns=cols, show="headings",
                                   style="Analytics.Treeview", selectmode="browse",
                                   height=12)

        col_cfg = [
            ("full_name",      "ФИО менеджера",        220, "w"),
            ("total_kp",       "КП за период",          120, "center"),
            ("total_items",    "Позиций",               120, "center"),
            ("avg_items",      "Ср. поз./КП",           110, "center"),
            ("last_activity",  "Последняя активность",  160, "center"),
        ]
        for col, heading, width, anchor in col_cfg:
            self._tree.heading(col, text=heading,
                               command=lambda c=col: self._sort_tree(c, False))
            self._tree.column(col, width=width, anchor=anchor, minwidth=80)

        vsb = ttk.Scrollbar(tbl_wrap, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.tag_configure("odd",  background="#F8FAFB")
        self._tree.tag_configure("even", background=BG_CARD)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # ── Пустой лейбл, если нет данных ─────────────────────────────────────
        self._empty_lbl = ctk.CTkLabel(
            scroll, text="Нет данных за выбранный период",
            font=FONT_NORMAL, text_color=TEXT_SECONDARY,
        )

    # ── Загрузка данных ───────────────────────────────────────────────────────

    def _on_period_change(self, label: str):
        for lbl, days in PERIOD_OPTIONS:
            if lbl == label:
                self._period = days
                break
        self.load()

    def load(self):
        """Загружает summary + KPI, вызывается при открытии вкладки."""
        if self._loading:
            return
        self._loading = True
        self._status_lbl.configure(text="⏳  Загрузка аналитики…")
        self._empty_lbl.grid_remove()
        for card in self._cards:
            card.set("…")
        self._avg_lbl.configure(text="")
        self._tree.delete(*self._tree.get_children())
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            summary = self.api.get_analytics_summary(self._period)
            kpi     = self.api.get_analytics_kpi(self._period)
            self.after(0, lambda: self._render(summary, kpi))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._on_error(msg))
        finally:
            self._loading = False

    def _render(self, summary: dict, kpi: dict):
        self._status_lbl.configure(text="")

        # Карточки
        values = [
            summary.get("total_kp",        0),
            summary.get("total_items",      0),
            summary.get("active_managers",  0),
            summary.get("total_errors",     0),
        ]
        for card, v in zip(self._cards, values):
            card.set(f"{v:,}".replace(",", " "))

        avg = summary.get("avg_items_per_kp", 0)
        self._avg_lbl.configure(
            text=f"Среднее позиций на КП: {avg}"
        )

        # KPI таблица
        self._tree.delete(*self._tree.get_children())
        managers = kpi.get("managers", [])
        if not managers:
            self._empty_lbl.grid(row=5, column=0, pady=8)
        else:
            self._empty_lbl.grid_remove()
            for i, m in enumerate(managers):
                tag = "odd" if i % 2 else "even"
                self._tree.insert("", "end", tags=(tag,), values=(
                    m.get("full_name",     "—"),
                    m.get("total_kp",       0),
                    m.get("total_items",    0),
                    m.get("avg_items",      0),
                    m.get("last_activity", "—"),
                ))

    def _on_error(self, msg: str):
        self._status_lbl.configure(text=f"⚠️  Ошибка загрузки: {msg}")
        for card in self._cards:
            card.set("—")

    # ── Сортировка таблицы ────────────────────────────────────────────────────

    def _sort_tree(self, col: str, reverse: bool):
        data = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        try:
            data.sort(key=lambda x: float(x[0].replace(" ", "")), reverse=reverse)
        except ValueError:
            data.sort(key=lambda x: x[0].lower(), reverse=reverse)
        for idx, (_, k) in enumerate(data):
            self._tree.move(k, "", idx)
            tag = "odd" if idx % 2 else "even"
            self._tree.item(k, tags=(tag,))
        self._tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    # ── Хук после логина ──────────────────────────────────────────────────────

    def after_login(self):
        """Вызывается из main_window после успешного логина."""
        self.after(300, self.load)
