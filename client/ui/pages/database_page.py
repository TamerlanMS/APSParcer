import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import threading, os

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService, SessionExpiredError

try:
    from tkinterdnd2 import DND_FILES
except Exception:
    DND_FILES = "DND_Files"


class DropCard(ctk.CTkFrame):
    """Drag-and-drop card for xlsx files."""
    def __init__(self, parent, label_key: str, **kwargs):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_LG,
                         border_width=2, border_color="#AEB6BF", **kwargs)
        self.label_key = label_key
        self._path     = None

        self.lbl = ctk.CTkLabel(self,
                                 text=f"📂  {t(label_key)}\n\nПеретащите .xlsx или нажмите для выбора",
                                 font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                 wraplength=500)
        self.lbl.pack(pady=(28, 8))

        self.status_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
                                        text_color=NAVY_LIGHT)
        self.status_lbl.pack(pady=(0, 24))

        self.bind("<Button-1>", lambda e: self._browse())
        self.lbl.bind("<Button-1>", lambda e: self._browse())
        for w in (self, self.lbl, self.status_lbl):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception as e:
                print(f"[DnD/DropCard] {w}: {e}")

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*.*")]
        )
        if path:
            self._set(path)

    def _on_drop(self, event):
        raw = (event.data or "").strip()
        if raw.startswith("{"):
            end = raw.find("}")
            path = raw[1:end] if end > 0 else raw.strip("{}")
        else:
            path = raw.split()[0] if raw else ""
        if path.lower().endswith((".xlsx", ".xlsm")):
            self._set(path)

    def _set(self, path: str):
        self._path = path
        name = os.path.basename(path)
        self.status_lbl.configure(text=f"✅  {name}")
        self.configure(border_color=NAVY_LIGHT, fg_color=BLUE_PALE)

    def get_path(self):
        return self._path

    def refresh_lang(self):
        self.lbl.configure(text=f"📂  {t(self.label_key)}\n\nПеретащите .xlsx или нажмите для выбора")


class DatabasePage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api = api
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build()
        self._apply_role_visibility()

    def _is_admin(self) -> bool:
        try:
            return self.app.config.user_role in ("superadmin", "administrator", "admin")
        except Exception:
            return False

    def _apply_role_visibility(self):
        """Показывает элементы согласно роли: admin — полный доступ,
        manager — только свой сегмент, director — раздел скрыт в nav."""
        if not hasattr(self, "_vectorize_btn"):
            return
        if self._is_admin():
            # Администратор: выбор сегмента импорта + блок векторизации + статистика
            self._seg_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._vec_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._stats_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._settings_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._seg_info_lbl.grid_remove()
            self._refresh_stats()
            self._refresh_budget()
            self._load_settings()
        else:
            # Менеджер: только импорт в свой сегмент, векторизация скрыта
            self._seg_frame.grid_remove()
            self._vec_frame.grid_remove()
            self._stats_frame.grid_remove()
            self._settings_frame.grid_remove()
            seg_code = getattr(self.app.config, "user_segment", "ss")
            seg_map  = {"ss": "Слаботочные системы", "os": "Осветительные системы",
                        "sil": "Силовые системы"}
            seg_name = seg_map.get(seg_code, seg_code.upper())
            self._seg_info_lbl.configure(
                text=f"🗂  Ваш сегмент: {seg_name}"
            )
            self._seg_info_lbl.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 4))

    def _enforce_role_layout(self, _event=None):
        """Лёгкая версия _apply_role_visibility без API-запросов.
        Вызывается при Configure-событиях CTkTabview чтобы предотвратить
        повторный показ скрытых фреймов при перемещении окна."""
        if not hasattr(self, "_vectorize_btn"):
            return
        if self._is_admin():
            self._seg_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._vec_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._stats_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 8))
            self._settings_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 8))
        else:
            self._seg_frame.grid_remove()
            self._vec_frame.grid_remove()
            self._stats_frame.grid_remove()
            self._settings_frame.grid_remove()

    def _build(self):
        pad = PAD_MD

        # ── Header ────────────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(PAD_MD, 8))
        top.grid_columnconfigure(1, weight=1)

        self.title_lbl = ctk.CTkLabel(top, text=t("db_title"),
                                       font=FONT_TITLE, text_color=NAVY)
        self.title_lbl.grid(row=0, column=0, sticky="w")

        self.count_lbl = ctk.CTkLabel(top, text=t("db_count", count="..."),
                                       font=FONT_NORMAL, text_color=NAVY_LIGHT)
        self.count_lbl.grid(row=0, column=1, padx=16, sticky="w")

        self.refresh_btn = ctk.CTkButton(
            top, text=t("db_refresh"), font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=130, corner_radius=RADIUS_SM,
            command=self._refresh_count
        )
        self.refresh_btn.grid(row=0, column=2)

        # ── Tabview (Import + Logs) ───────────────────────────────────────────
        self.tabview = ctk.CTkTabview(
            self, fg_color=BG_CARD, corner_radius=RADIUS_MD,
            segmented_button_fg_color=NAVY,
            segmented_button_selected_color=NAVY_LIGHT,
            segmented_button_unselected_color=BLUE_MID,
            segmented_button_selected_hover_color=BLUE_LIGHT,
            text_color="white", text_color_disabled=TEXT_NAV,
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, pad))
        self.tabview.add(t("db_tab_import"))
        self.tabview.add("Бренды")
        self.tabview.add("Прейскурант")
        self.tabview.add(t("db_tab_logs"))

        self._build_import_tab()
        self._build_brands_tab()
        self._build_pricelist_tab()
        self._build_logs_tab()

        # Автозагрузка логов при переключении на вкладку «История»
        self.tabview.configure(command=self._on_tab_change)

        # ── Progress / status (shared) ────────────────────────────────────────
        self.progress = ctk.CTkProgressBar(self, progress_color=NAVY_LIGHT,
                                            fg_color="#D5D8DC")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, 4))
        self.progress.grid_remove()

        self.status_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
                                        text_color=TEXT_SECONDARY)
        self.status_lbl.grid(row=3, column=0, pady=(0, pad))

        self._refresh_count()

    def _build_import_tab(self):
        _tab_root = self.tabview.tab(t("db_tab_import"))
        _tab_root.grid_rowconfigure(0, weight=1)
        _tab_root.grid_columnconfigure(0, weight=1)

        # Содержимое не помещается по высоте на небольших экранах — иначе grid
        # ужимает последний блок до нулевой высоты. Кладём всё в скролл-контейнер.
        self._import_scroll = ctk.CTkScrollableFrame(
            _tab_root, fg_color="transparent", corner_radius=0,
        )
        self._import_scroll.grid(row=0, column=0, sticky="nsew")
        self._import_scroll.grid_columnconfigure(0, weight=1)

        tab = self._import_scroll
        tab.grid_columnconfigure(0, weight=1)

        self.db_desc = ctk.CTkLabel(
            tab, text=t("db_import_both_desc"),
            font=FONT_NORMAL, text_color=TEXT_SECONDARY,
            wraplength=700, anchor="w",
        )
        self.db_desc.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        # Single drop zone for both DB and Constants
        self.db_drop = DropCard(tab, "db_drop_label")
        self.db_drop.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        # ── Метка сегмента (только для менеджеров) ──────────────────────────────
        self._seg_info_lbl = ctk.CTkLabel(
            tab,
            text="",
            font=FONT_SMALL,
            text_color=NAVY_LIGHT,
        )
        self._seg_info_lbl.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 4))
        self._seg_info_lbl.grid_remove()

        # ── Segment selector (только для администраторов) ─────────────────────
        self._seg_frame = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        self._seg_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._seg_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._seg_frame, text=t("db_import_seg_label"),
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=0, column=0, padx=(12, 8), pady=8, sticky="w")

        seg_labels = [t("seg_ss"), t("seg_os"), t("seg_sil")]
        self._import_seg_var = ctk.StringVar(value=seg_labels[0])
        self._import_seg_btn = ctk.CTkSegmentedButton(
            self._seg_frame,
            values=seg_labels,
            variable=self._import_seg_var,
            font=FONT_SMALL,
            selected_color=NAVY,
            selected_hover_color=NAVY_DARK,
            unselected_color="#5D6D7E",
            unselected_hover_color="#4A5568",
            text_color="white",
            text_color_disabled="#AABBCC",
            dynamic_resizing=False,
            height=32,
        )
        self._import_seg_btn.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="ew")

        # Warning hint
        ctk.CTkLabel(
            self._seg_frame,
            text="⚠  Выберите сегмент базы перед импортом (SS / OS / SIL)",
            font=(*FONT_SMALL[:2], "italic"),
            text_color="#B45309",
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="w")

        # map label→code for lookup
        self._import_seg_labels = seg_labels
        self._import_seg_codes  = ["ss", "os", "sil"]
        self._seg_frame.grid_remove()   # скрыт по умолчанию, показывается для admin

        # Single combined import button
        self.db_btn = ctk.CTkButton(
            tab, text=t("db_import_both_btn"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=44, corner_radius=RADIUS_MD,
            command=self._import_both,
        )
        self.db_btn.grid(row=3, column=0, padx=16, pady=(8, 8), sticky="ew")

        # ── Векторизация (только для администраторов) ────────────────────────
        self._vec_frame = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        self._vec_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._vec_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._vec_frame, text="Векторизация:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=0, column=0, padx=(12, 8), pady=8, sticky="w")

        _vec_labels = [t("seg_ss"), t("seg_os"), t("seg_sil"), "Все сегменты"]
        self._vec_seg_var = ctk.StringVar(value=_vec_labels[3])  # default: Все
        self._vec_seg_btn = ctk.CTkSegmentedButton(
            self._vec_frame,
            values=_vec_labels,
            variable=self._vec_seg_var,
            font=FONT_SMALL,
            selected_color="#2C3E50",
            selected_hover_color="#1A252F",
            unselected_color="#5D6D7E",
            unselected_hover_color="#4A5568",
            text_color="white",
            text_color_disabled="#AABBCC",
            dynamic_resizing=False,
            height=32,
        )
        self._vec_seg_btn.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="ew")
        self._vec_seg_labels = _vec_labels
        self._vec_seg_codes  = ["ss", "os", "sil", "all"]

        self._vectorize_btn = ctk.CTkButton(
            self._vec_frame, text="🔄  Начать",
            font=FONT_SMALL,
            fg_color="#2C3E50", hover_color="#1A252F",
            height=32, width=110, corner_radius=RADIUS_SM,
            command=self._start_vectorization,
        )
        self._vectorize_btn.grid(row=0, column=2, padx=(0, 12), pady=6)

        self._reconnect_btn = ctk.CTkButton(
            self._vec_frame, text="🔌 Переподключить",
            font=FONT_SMALL, fg_color="#4A235A", hover_color="#2E1538",
            height=32, width=150, corner_radius=RADIUS_SM,
            command=self._reconnect_pinecone,
        )
        self._reconnect_btn.grid(row=0, column=3, padx=(0, 12), pady=6)

        # Budget row
        ctk.CTkLabel(
            self._vec_frame, text="Бюджет сегодня:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=1, column=0, padx=(12, 8), pady=(0, 8), sticky="w")

        self._budget_lbl = ctk.CTkLabel(
            self._vec_frame, text="—",
            font=FONT_SMALL, text_color=TEXT_PRIMARY,
        )
        self._budget_lbl.grid(row=1, column=1, padx=(0, 8), pady=(0, 8), sticky="w")

        self._budget_refresh_btn = ctk.CTkButton(
            self._vec_frame, text="↻",
            font=FONT_SMALL, fg_color="#2C3E50", hover_color="#1A252F",
            height=24, width=36, corner_radius=RADIUS_SM,
            command=self._refresh_budget,
        )
        self._budget_refresh_btn.grid(row=1, column=2, padx=(0, 12), pady=(0, 8))

        self._vec_frame.grid_remove()  # скрыт по умолчанию

        # ── Статистика по сегментам + кнопка очистки (только для admin) ──────
        self._stats_frame = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        self._stats_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 8))
        self._stats_frame.grid_columnconfigure(1, weight=1)
        self._stats_frame.grid_remove()

        ctk.CTkLabel(
            self._stats_frame, text="Статистика БД:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=0, column=0, padx=(12, 8), pady=(10, 2), sticky="w")

        self._stats_lbl = ctk.CTkLabel(
            self._stats_frame, text="—",
            font=FONT_SMALL, text_color=TEXT_PRIMARY,
        )
        self._stats_lbl.grid(row=0, column=1, padx=(0, 8), pady=(10, 2), sticky="w")

        self._stats_refresh_btn = ctk.CTkButton(
            self._stats_frame, text="↻",
            font=FONT_SMALL, fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=28, width=36, corner_radius=RADIUS_SM,
            command=self._refresh_stats,
        )
        self._stats_refresh_btn.grid(row=0, column=2, padx=(0, 8), pady=(10, 2))

        ctk.CTkLabel(
            self._stats_frame, text="Очистить сегмент:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=1, column=0, padx=(12, 8), pady=(4, 10), sticky="w")

        _clear_seg_labels = [t("seg_ss"), t("seg_os"), t("seg_sil")]
        self._clear_seg_var = ctk.StringVar(value=_clear_seg_labels[0])
        self._clear_seg_btn = ctk.CTkSegmentedButton(
            self._stats_frame,
            values=_clear_seg_labels,
            variable=self._clear_seg_var,
            font=FONT_SMALL,
            selected_color="#7B2D00", selected_hover_color="#5C1F00",
            unselected_color="#5D6D7E", unselected_hover_color="#4A5568",
            text_color="white", dynamic_resizing=False, height=28,
        )
        self._clear_seg_btn.grid(row=1, column=1, padx=(0, 8), pady=(4, 10), sticky="ew")
        self._clear_seg_labels = _clear_seg_labels
        self._clear_seg_codes  = ["ss", "os", "sil"]

        self._do_clear_btn = ctk.CTkButton(
            self._stats_frame, text="🗑 Очистить",
            font=FONT_SMALL, fg_color="#7B2D00", hover_color="#5C1F00",
            height=28, width=110, corner_radius=RADIUS_SM,
            command=self._clear_segment,
        )
        self._do_clear_btn.grid(row=1, column=2, padx=(0, 8), pady=(4, 10))

        # ── Настройки ценообразования (только администратор) ─────────────
        self._settings_frame = ctk.CTkFrame(tab, fg_color=BG_CARD,
                                            corner_radius=RADIUS_MD)
        self._settings_frame.grid(row=6, column=0, sticky="ew",
                                  padx=16, pady=(0, 8))
        self._settings_frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            self._settings_frame, text="⚙  Ценообразование",
            font=FONT_NORMAL, text_color=NAVY,
        ).grid(row=0, column=0, columnspan=4, sticky="w",
               padx=12, pady=(10, 2))

        ctk.CTkLabel(
            self._settings_frame,
            text=("Применяется к позициям без кода АГСК или с пустой ценой КазНИИСА:\n"
                  "Предварительная цена = Проектная (Партнёр/проект/дистр.) × коэффициент"),
            font=FONT_SMALL, text_color=TEXT_SECONDARY, justify="left",
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            self._settings_frame, text="Коэффициент:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).grid(row=2, column=0, padx=(12, 8), pady=(0, 10), sticky="w")

        self._coeff_var = ctk.StringVar(value="2.5")
        self._coeff_entry = ctk.CTkEntry(
            self._settings_frame, textvariable=self._coeff_var,
            width=100, height=28, font=FONT_SMALL, corner_radius=RADIUS_SM,
        )
        self._coeff_entry.grid(row=2, column=1, padx=(0, 8), pady=(0, 10), sticky="w")

        self._coeff_save_btn = ctk.CTkButton(
            self._settings_frame, text="Сохранить",
            font=FONT_SMALL, fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=28, width=110, corner_radius=RADIUS_SM,
            command=self._save_settings,
        )
        self._coeff_save_btn.grid(row=2, column=2, padx=(0, 8), pady=(0, 10))

        self._settings_status = ctk.CTkLabel(
            self._settings_frame, text="", font=FONT_SMALL,
            text_color=TEXT_SECONDARY, anchor="w",
        )
        self._settings_status.grid(row=2, column=3, padx=(0, 12),
                                   pady=(0, 10), sticky="w")

        # Привязываем Configure чтобы CTkTabview не «поднимал» скрытые фреймы при
        # перемещении или изменении размера окна
        tab.bind("<Configure>", self._enforce_role_layout, add="+")

    def _build_brands_tab(self):
        tab = self.tabview.tab("Бренды")
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        # ── Top bar: поиск + обновить ──────────────────────────────────────────
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 4))
        top.grid_columnconfigure(0, weight=1)

        self._brand_search_var = ctk.StringVar()
        self._brand_search_var.trace_add("write", lambda *_: self._filter_brands())
        ctk.CTkEntry(
            top, textvariable=self._brand_search_var,
            placeholder_text="🔍  Фильтр по бренду...",
            font=FONT_SMALL, height=32,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            top, text="↻ Обновить", font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=120, corner_radius=RADIUS_SM,
            command=self._load_brand_stats,
        ).grid(row=0, column=1)

        # ── Легенда цветов ────────────────────────────────────────────────────
        legend = ctk.CTkFrame(tab, fg_color="transparent")
        legend.grid(row=0, column=0, columnspan=2, sticky="e", padx=16)
        for txt, color in [
            ("▮ увеличение", "#27AE60"),
            ("▮ уменьшение", "#E74C3C"),
            ("▮ новый бренд", "#2980B9"),
            ("▮ удалён", "#E67E22"),
        ]:
            ctk.CTkLabel(legend, text=txt, font=FONT_SMALL,
                         text_color=color).pack(side="left", padx=(0, 10))

        # ── Treeview ──────────────────────────────────────────────────────────
        style = ttk.Style()
        style.configure("Brand.Treeview", rowheight=24, font=("Calibri", 11))
        style.configure("Brand.Treeview.Heading",
                        background=NAVY, foreground="white",
                        font=("Calibri", 11, "bold"))

        cols = ["brand", "ss", "os", "sil", "total", "delta"]
        self._brand_tree = ttk.Treeview(
            tab, columns=cols, show="headings", style="Brand.Treeview"
        )
        for col, hdr, w, anc in zip(
            cols,
            ["Бренд", "SS", "OS", "SIL", "Всего", "Δ изменение"],
            [200, 65, 65, 65, 80, 110],
            ["w", "center", "center", "center", "center", "center"],
        ):
            self._brand_tree.heading(col, text=hdr,
                                     command=lambda c=col: self._sort_brands(c))
            self._brand_tree.column(col, width=w, anchor=anc, minwidth=40)

        vsb = ttk.Scrollbar(tab, orient="vertical", command=self._brand_tree.yview)
        self._brand_tree.configure(yscrollcommand=vsb.set)
        self._brand_tree.grid(row=1, column=0, sticky="nsew",
                               padx=(16, 0), pady=(4, 4))
        vsb.grid(row=1, column=1, sticky="ns", pady=(4, 4), padx=(0, 16))

        self._brand_tree.tag_configure("increased", background="#D4EDDA")
        self._brand_tree.tag_configure("decreased", background="#F8D7DA")
        self._brand_tree.tag_configure("new_brand", background="#D1ECF1")
        self._brand_tree.tag_configure("removed",   background="#FFF3CD")

        # ── Итоговая строка ───────────────────────────────────────────────────
        self._brand_summary_lbl = ctk.CTkLabel(
            tab, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self._brand_summary_lbl.grid(row=2, column=0, pady=(0, 10))

        # ── Данные ────────────────────────────────────────────────────────────
        self._brand_data: list = []
        self._prev_brand_stats: dict = {}
        self._brand_sort_col   = "total"
        self._brand_sort_asc   = False

    def _load_settings(self):
        """Читает текущие настройки с сервера в фоне."""
        def _work():
            try:
                data = self.api.get_app_settings() or {}
                coeff = float(data.get("prelim_price_coeff") or 2.5)
            except Exception as e:
                self.after(0, lambda: self._settings_status.configure(
                    text=f"Не удалось загрузить настройки: {e}"))
                return
            def _apply():
                self._coeff_var.set(f"{coeff:g}")
                self._settings_status.configure(text="")
            self.after(0, _apply)

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _save_settings(self):
        """Сохраняет коэффициент на сервере."""
        raw = (self._coeff_var.get() or "").strip().replace(",", ".")
        try:
            coeff = float(raw)
        except ValueError:
            self._settings_status.configure(
                text="Коэффициент должен быть числом", text_color="#C0392B")
            return
        if coeff <= 0:
            self._settings_status.configure(
                text="Коэффициент должен быть больше нуля", text_color="#C0392B")
            return

        self._coeff_save_btn.configure(state="disabled")
        self._settings_status.configure(text="Сохранение...",
                                        text_color=TEXT_SECONDARY)

        def _work():
            try:
                self.api.update_app_settings(prelim_price_coeff=coeff)
            except Exception as e:
                self.after(0, lambda: (
                    self._settings_status.configure(
                        text=f"Ошибка сохранения: {e}", text_color="#C0392B"),
                    self._coeff_save_btn.configure(state="normal"),
                ))
                return
            self.after(0, lambda: (
                self._settings_status.configure(
                    text=f"Сохранено: коэффициент {coeff:g}. "
                         f"Изменения применятся при следующей загрузке файла.",
                    text_color=NAVY_LIGHT),
                self._coeff_save_btn.configure(state="normal"),
            ))

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _build_pricelist_tab(self):
        """Сверка цен базы со сметными ценами прейскуранта АГСК."""
        tab = self.tabview.tab("Прейскурант")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab,
            text=("Сверка цен КазНИИСА из базы со сметными ценами прейскуранта.\n"
                  "Сопоставление строго по коду АГСК; сметная цена — верхнее "
                  "число в ячейке прейскуранта."),
            font=FONT_NORMAL, text_color=TEXT_SECONDARY,
            wraplength=760, anchor="w", justify="left",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 10))

        # ── Две зоны: прейскурант и эксель-база ──────────────────────────────
        self._pl_path   = ""
        self._pl_base_path = ""

        zones = ctk.CTkFrame(tab, fg_color="transparent")
        zones.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        zones.grid_columnconfigure(0, weight=1, uniform="plz")
        zones.grid_columnconfigure(1, weight=1, uniform="plz")

        # Прейскурант (PDF)
        self._pl_drop = ctk.CTkFrame(
            zones, fg_color=BG_CARD, corner_radius=RADIUS_LG,
            border_width=2, border_color="#AEB6BF",
        )
        self._pl_drop.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(self._pl_drop, text="ПРЕЙСКУРАНТ",
                     font=(*FONT_SMALL[:2], "bold"),
                     text_color=NAVY).pack(pady=(12, 0))
        self._pl_drop_lbl = ctk.CTkLabel(
            self._pl_drop,
            text="📄  Перетащите прейскурант (PDF)\n\nили нажмите для выбора",
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, wraplength=340,
        )
        self._pl_drop_lbl.pack(pady=(10, 6))
        self._pl_file_lbl = ctk.CTkLabel(
            self._pl_drop, text="", font=FONT_SMALL, text_color=NAVY_LIGHT,
            wraplength=340,
        )
        self._pl_file_lbl.pack(pady=(0, 6))
        ctk.CTkButton(
            self._pl_drop, text="Выбрать файл", font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY, height=28, width=140,
            corner_radius=RADIUS_SM, command=self._pl_browse,
        ).pack(pady=(0, 14))

        for _w in (self._pl_drop, self._pl_drop_lbl, self._pl_file_lbl):
            _w.bind("<Button-1>", lambda e: self._pl_browse())
            try:
                _w.drop_target_register(DND_FILES)
                _w.dnd_bind("<<Drop>>", self._pl_on_drop)
            except Exception as e:
                print(f"[DnD/Прейскурант] {_w}: {e}")

        # Эксель-база сегмента
        self._pl_base_drop = ctk.CTkFrame(
            zones, fg_color=BG_CARD, corner_radius=RADIUS_LG,
            border_width=2, border_color="#AEB6BF",
        )
        self._pl_base_drop.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(self._pl_base_drop, text="БАЗА СЕГМЕНТА",
                     font=(*FONT_SMALL[:2], "bold"),
                     text_color=NAVY).pack(pady=(12, 0))
        self._pl_base_lbl = ctk.CTkLabel(
            self._pl_base_drop,
            text="📊  Перетащите эксель-базу (.xlsx / .xlsm)\n\n"
                 "необязательно — без неё сверка идёт с БД",
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, wraplength=340,
        )
        self._pl_base_lbl.pack(pady=(10, 6))
        self._pl_base_file_lbl = ctk.CTkLabel(
            self._pl_base_drop, text="", font=FONT_SMALL,
            text_color=NAVY_LIGHT, wraplength=340,
        )
        self._pl_base_file_lbl.pack(pady=(0, 6))

        _bb = ctk.CTkFrame(self._pl_base_drop, fg_color="transparent")
        _bb.pack(pady=(0, 14))
        ctk.CTkButton(
            _bb, text="Выбрать файл", font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY, height=28, width=140,
            corner_radius=RADIUS_SM, command=self._pl_base_browse,
        ).pack(side="left", padx=(0, 6))
        self._pl_base_clear_btn = ctk.CTkButton(
            _bb, text="✕", font=FONT_SMALL,
            fg_color="#95A5A6", hover_color="#7F8C8D", height=28, width=34,
            corner_radius=RADIUS_SM, command=self._pl_base_clear,
        )

        for _w in (self._pl_base_drop, self._pl_base_lbl, self._pl_base_file_lbl):
            _w.bind("<Button-1>", lambda e: self._pl_base_browse())
            try:
                _w.drop_target_register(DND_FILES)
                _w.dnd_bind("<<Drop>>", self._pl_base_on_drop)
            except Exception as e:
                print(f"[DnD/База] {_w}: {e}")

        self._pl_browse_btn = None

        # ── Параметры сверки ─────────────────────────────────────────────────
        opts = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        opts.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts, text="Сегмент базы:", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY
                     ).grid(row=0, column=0, padx=(12, 8), pady=(10, 6), sticky="w")

        _pl_labels = [t("seg_ss"), t("seg_os"), t("seg_sil"), "Все"]
        self._pl_seg_var = ctk.StringVar(value=_pl_labels[0])
        self._pl_seg_btn = ctk.CTkSegmentedButton(
            opts, values=_pl_labels, variable=self._pl_seg_var,
            font=FONT_SMALL,
            selected_color="#2C3E50", selected_hover_color="#1A252F",
            unselected_color="#5D6D7E", unselected_hover_color="#4A5568",
            text_color="white", dynamic_resizing=False, height=32,
        )
        self._pl_seg_btn.grid(row=0, column=1, padx=(0, 8), pady=(10, 6), sticky="ew")
        self._pl_seg_labels = _pl_labels
        self._pl_seg_codes  = ["ss", "os", "sil", "all"]

        ctk.CTkLabel(opts, text="Порог отклонения, %:", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY
                     ).grid(row=1, column=0, padx=(12, 8), pady=(0, 10), sticky="w")

        self._pl_threshold_var = ctk.StringVar(value="5")
        ctk.CTkEntry(opts, textvariable=self._pl_threshold_var, width=80,
                     height=28, font=FONT_SMALL, corner_radius=RADIUS_SM
                     ).grid(row=1, column=1, pady=(0, 10), sticky="w")

        self._pl_run_btn = ctk.CTkButton(
            opts, text="Сверить цены", font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=36, width=170, corner_radius=RADIUS_SM,
            state="disabled", command=self._pl_run,
        )
        self._pl_run_btn.grid(row=0, column=2, rowspan=2, padx=12, pady=10)

        # Режимы сверки с приложенной эксель-базой
        _sync = ctk.CTkFrame(opts, fg_color="transparent")
        _sync.grid(row=2, column=0, columnspan=3, sticky="ew",
                   padx=12, pady=(0, 10))

        self._pl_cmp_btn = ctk.CTkButton(
            _sync, text="📋 Только сравнить", font=FONT_SMALL,
            fg_color="#5D6D7E", hover_color="#4A5568",
            height=32, width=200, corner_radius=RADIUS_SM,
            state="disabled", command=lambda: self._pl_sync_run(False),
        )
        self._pl_cmp_btn.pack(side="left", padx=(0, 8))

        self._pl_apply_btn = ctk.CTkButton(
            _sync, text="✔ Применить и загрузить", font=(*FONT_SMALL[:2], "bold"),
            fg_color="#1E8449", hover_color="#186A3B",
            height=32, width=230, corner_radius=RADIUS_SM,
            state="disabled", command=lambda: self._pl_sync_run(True),
        )
        self._pl_apply_btn.pack(side="left")

        ctk.CTkLabel(
            _sync,
            text="  Цены обновляются в приложенном файле (сметная × 1.16 → "
                 "колонка «КазНИИСА»),\n  несовпавшие позиции прейскуранта "
                 "идут в общую базу.",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
            anchor="w", justify="left",
        ).pack(side="left", padx=(10, 0))

        # ── Результаты ───────────────────────────────────────────────────────
        res = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD)
        res.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        res.grid_columnconfigure(0, weight=1)
        res.grid_rowconfigure(0, weight=1)

        # Построчный разбор живёт в отчёте Excel — здесь только итог
        self._pl_summary = ctk.CTkLabel(
            res, text="Выберите прейскурант и запустите сверку.\n\n"
                      "Построчный разбор сохраняется в отчёт Excel.",
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, anchor="nw",
            justify="left", wraplength=1000,
        )
        self._pl_summary.grid(row=0, column=0, sticky="nsew",
                              padx=16, pady=(14, 8))

        self._pl_save_btn = ctk.CTkButton(
            res, text="💾 Сохранить отчёт как...", font=FONT_SMALL,
            fg_color="#1E8449", hover_color="#186A3B",
            height=32, width=230, corner_radius=RADIUS_SM,
            state="disabled", command=self._pl_save_report,
        )
        self._pl_save_btn.grid(row=2, column=0, columnspan=2, sticky="e",
                               padx=12, pady=(0, 12))

        self._pl_result = None

    def _pl_browse(self):
        path = filedialog.askopenfilename(
            title="Выберите прейскурант",
            filetypes=[("PDF", "*.pdf"), ("Все файлы", "*.*")],
        )
        if path:
            self._pl_set_file(path)

    def _pl_on_drop(self, event):
        """Файл перетащен в зону — принимаем только PDF."""
        raw = (event.data or "").strip()
        if raw.startswith("{"):
            end = raw.find("}")
            path = raw[1:end] if end > 0 else raw.strip("{}")
        else:
            path = raw.split()[0] if raw else ""
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            messagebox.showwarning("", "Прейскурант должен быть в формате PDF.")
            return
        self._pl_set_file(path)

    def _pl_set_file(self, path: str):
        self._pl_path = path
        self._pl_file_lbl.configure(text=f"✅  {os.path.basename(path)}")
        self._pl_drop.configure(border_color=NAVY_LIGHT, fg_color=BLUE_PALE)
        self._pl_drop_lbl.configure(
            text="📄  Файл выбран — нажмите «Сверить цены»\n\n"
                 "или перетащите другой файл",
        )
        self._pl_run_btn.configure(state="normal")
        self._pl_sync_buttons()

    def _pl_base_browse(self):
        p = filedialog.askopenfilename(
            title="Выберите эксель-базу сегмента",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Все файлы", "*.*")],
        )
        if p:
            self._pl_set_base(p)

    def _pl_base_on_drop(self, event):
        raw = (event.data or "").strip()
        if raw.startswith("{"):
            end = raw.find("}")
            p = raw[1:end] if end > 0 else raw.strip("{}")
        else:
            p = raw.split()[0] if raw else ""
        if not p:
            return
        if not p.lower().endswith((".xlsx", ".xlsm")):
            messagebox.showwarning("", "База должна быть в формате .xlsx или .xlsm.")
            return
        self._pl_set_base(p)

    def _pl_set_base(self, path: str):
        self._pl_base_path = path
        self._pl_base_file_lbl.configure(text=f"✅  {os.path.basename(path)}")
        self._pl_base_drop.configure(border_color="#1E8449", fg_color="#EAF7EF")
        self._pl_base_lbl.configure(
            text="📊  База выбрана\n\nвыберите режим сверки ниже")
        self._pl_base_clear_btn.pack(side="left")
        self._pl_sync_buttons()

    def _pl_base_clear(self):
        self._pl_base_path = ""
        self._pl_base_file_lbl.configure(text="")
        self._pl_base_drop.configure(border_color="#AEB6BF", fg_color=BG_CARD)
        self._pl_base_lbl.configure(
            text="📊  Перетащите эксель-базу (.xlsx / .xlsm)\n\n"
                 "необязательно — без неё сверка идёт с БД")
        self._pl_base_clear_btn.pack_forget()
        self._pl_sync_buttons()

    def _pl_sync_buttons(self):
        """Режимы сверки доступны только когда выбраны оба файла."""
        state = "normal" if (self._pl_path and self._pl_base_path) else "disabled"
        for b in (self._pl_cmp_btn, self._pl_apply_btn):
            b.configure(state=state)

    def _pl_sync_run(self, apply_changes: bool):
        """Сверка приложенной эксель-базы с прейскурантом.

        apply_changes=False — только отчёт, ни файл, ни база не меняются.
        """
        if not (self._pl_path and self._pl_base_path):
            return
        if not os.path.isfile(self._pl_base_path):
            messagebox.showerror("", "Файл базы не найден.")
            return

        for b in (self._pl_cmp_btn, self._pl_apply_btn, self._pl_run_btn):
            b.configure(state="disabled")
        self.progress.grid()
        self.progress.set(0)
        self._pl_summary.configure(
            text="Разбор прейскуранта. На большом файле это занимает "
                 "несколько минут...",
            text_color=TEXT_SECONDARY)

        def _progress(pct, stage, msg):
            self.after(0, lambda: (self.progress.set(max(0.0, min(1.0, pct / 100))),
                                   self._pl_summary.configure(text=msg)))

        def _worker():
            try:
                from services.pricelist_sync import (
                    read_base_rows, match_base_to_pricelist,
                )

                parsed  = self.api.parse_pricelist(self._pl_path, _progress)
                entries = parsed.get("entries") or {}
                if not entries:
                    raise RuntimeError("Прейскурант не содержит позиций с ценами.")

                self.after(0, lambda: self._pl_summary.configure(
                    text=f"Разобрано позиций: {len(entries):,}. Чтение базы..."))
                base_rows, sheet = read_base_rows(self._pl_base_path)
                if not base_rows:
                    raise RuntimeError(
                        "В файле базы не найдено строк. Ожидается лист «БД» "
                        "с колонками: № | Артикул | Наименование | Ед. | КазНИИСА ...")

                result = match_base_to_pricelist(
                    base_rows, entries,
                    progress_cb=lambda p, m: _progress(p, "match", m),
                )
                result["_sheet"] = sheet
            except Exception as e:
                self.after(0, lambda err=e: self._pl_sync_failed(err))
                return
            self.after(0, lambda: self._pl_sync_ready(result, apply_changes))

        threading.Thread(target=_worker, daemon=True).start()

    def _pl_sync_failed(self, exc: Exception):
        self.progress.grid_remove()
        self._pl_run_btn.configure(state="normal")
        self._pl_sync_buttons()
        self._pl_summary.configure(text=f"❌  {exc}", text_color="#E74C3C")
        self._handle_api_error(exc, "сверка с прейскурантом")

    def _pl_sync_ready(self, result: dict, apply_changes: bool):
        """Сопоставление готово: показываем итоги и, если нужно, применяем."""
        st = result["stats"]
        self.progress.set(1.0)

        # Насколько сильно меняются цены — единственная цифра, ради которой
        # стоило бы листать таблицу; показываем её сразу
        big = sum(1 for m in result["changed"]
                  if (m.get("diff_pct") or 0) and abs(m["diff_pct"]) > 100)

        self._pl_summary.configure(
            text=(f"Строк в базе: {st['base_rows']:,}   |   "
                  f"кодов в прейскуранте: {st['pricelist_codes']:,}   |   "
                  f"сопоставлено: {st['matched']:,} "
                  f"(код {st['by_code']:,}, артикул {st['by_article']:,})\n"
                  f"Цена изменится у {st['changed']:,} поз.   |   "
                  f"не опознано в базе: {st['unmatched_base']:,}   |   "
                  f"в общую базу: {st['to_general']:,}"
                  + (f"\n\n⚠  У {big:,} поз. цена меняется больше чем в 2 раза — "
                     f"проверьте их в отчёте перед применением."
                     if big else "")
                  + "\n\nПострочный разбор — в отчёте Excel."),
            text_color=NAVY)

        self._pl_sync_result   = result
        self._pl_sync_applied  = apply_changes
        self._pl_result = None          # отчёт старого режима больше не актуален
        self._pl_save_btn.configure(state="normal")

        if not apply_changes:
            self.progress.grid_remove()
            self._pl_run_btn.configure(state="normal")
            self._pl_sync_buttons()
            self._pl_summary.configure(
                text="📋  ТОЛЬКО СРАВНЕНИЕ — файл базы не изменён, "
                     "в базу ничего не загружено\n"
                     + self._pl_summary.cget("text"),
                text_color=NAVY)
            self._pl_sync_report(result, applied=False, backup="", loaded=False)
            return

        ok = messagebox.askyesno(
            "Применить изменения",
            f"Будет изменено цен: {st['changed']:,}\n"
            f"Загружено в общую базу: {st['to_general']:,}\n\n"
            f"Файл: {os.path.basename(self._pl_base_path)}\n"
            f"Перед изменением рядом будет создана копия с текущей датой.\n\n"
            f"Продолжить?",
            icon="warning", parent=self,
        )
        if not ok:
            self.progress.grid_remove()
            self._pl_run_btn.configure(state="normal")
            self._pl_sync_buttons()
            self._pl_summary.configure(
                text=self._pl_summary.cget("text") + "\n\nИзменения не применялись.",
                text_color=TEXT_SECONDARY)
            return

        self.progress.set(0)
        self._pl_summary.configure(text="Создание копии и запись цен...",
                                   text_color=TEXT_SECONDARY)

        def _worker():
            backup = ""
            loaded = False
            try:
                from services.pricelist_sync import (
                    make_dated_backup, write_prices_to_base,
                )
                backup = make_dated_backup(self._pl_base_path)
                written = write_prices_to_base(
                    self._pl_base_path, result["changed"], result.get("_sheet", ""))

                gen = [{"kaznisa_code": e["code"],
                        "name":         e.get("name", ""),
                        "unit":         e.get("unit", "") or "шт.",
                        "kaznisa":      round(float(e["price"]) * 1.16, 2)}
                       for e in result["unmatched_pricelist"]]
                res_gen = {"added": 0, "updated": 0}
                if gen:
                    self.after(0, lambda: self._pl_summary.configure(
                        text=f"Загрузка {len(gen):,} поз. в общую базу..."))
                    res_gen = self.api.pricelist_to_general(gen)
                    loaded = True
            except Exception as e:
                self.after(0, lambda err=e, b=backup: self._pl_apply_failed(err, b))
                return
            self.after(0, lambda: self._pl_apply_done(
                result, written, res_gen, backup, loaded))

        threading.Thread(target=_worker, daemon=True).start()

    def _pl_apply_failed(self, exc: Exception, backup: str):
        self.progress.grid_remove()
        self._pl_run_btn.configure(state="normal")
        self._pl_sync_buttons()
        tail = (f"\n\nКопия файла сохранена: {os.path.basename(backup)}"
                if backup else "")
        self._pl_summary.configure(text=f"❌  {exc}", text_color="#E74C3C")
        messagebox.showerror("Сверка с прейскурантом", f"{exc}{tail}", parent=self)

    def _pl_apply_done(self, result: dict, written: int, res_gen: dict,
                       backup: str, loaded: bool):
        self.progress.set(1.0)
        self.progress.grid_remove()
        self._pl_run_btn.configure(state="normal")
        self._pl_sync_buttons()
        self._refresh_count()
        self._load_brand_stats()

        self._pl_summary.configure(
            text=(f"✅  Обновлено цен: {written:,}   |   "
                  f"в общую базу добавлено {res_gen.get('added', 0):,}, "
                  f"обновлено {res_gen.get('updated', 0):,}\n"
                  f"Копия до изменений: {os.path.basename(backup)}"),
            text_color="#1E8449")

        self._pl_sync_report(result, applied=True, backup=backup, loaded=loaded)

    def _pl_sync_report(self, result: dict, applied: bool,
                        backup: str, loaded: bool):
        """Складывает отчёт рядом с файлом базы и предлагает открыть."""
        try:
            from services.pricelist_sync_report import (
                build_sync_report, default_report_path,
            )
            out = default_report_path(self._pl_base_path)
            build_sync_report(out, result, self._pl_base_path,
                              os.path.basename(self._pl_path),
                              applied=applied, backup=backup, loaded=loaded)
        except Exception as e:
            messagebox.showwarning("Отчёт", f"Не удалось сохранить отчёт: {e}",
                                   parent=self)
            return

        head = ("Цены записаны в файл базы."
                if applied else
                "Файл базы НЕ изменялся, в базу ничего не загружено.")
        if messagebox.askyesno(
            "Отчёт готов" if applied else "Сравнение готово",
            f"{head}\n\nОтчёт сохранён отдельным файлом:\n{out}\n\nОткрыть?",
            parent=self,
        ):
            try:
                os.startfile(out)          # noqa: S606 — Windows-клиент
            except Exception:
                pass

    def _pl_segments(self):
        try:
            idx = self._pl_seg_labels.index(self._pl_seg_var.get())
        except ValueError:
            idx = 0
        code = self._pl_seg_codes[idx]
        return ["ss", "os", "sil"] if code == "all" else [code]

    def _pl_run(self):
        if not self._pl_path:
            return
        try:
            threshold = float((self._pl_threshold_var.get() or "5").replace(",", "."))
        except ValueError:
            messagebox.showwarning("", "Порог отклонения должен быть числом.")
            return
        if threshold <= 0:
            messagebox.showwarning("", "Порог должен быть больше нуля.")
            return

        segs = self._pl_segments()
        self._pl_run_btn.configure(state="disabled", text="Сверка...")
        self._pl_save_btn.configure(state="disabled")
        self.progress.grid()
        self.progress.set(0)
        self._pl_summary.configure(
            text="Разбор прейскуранта. На большом файле это занимает несколько минут...")

        def _prog(pct, stage, msg):
            self.after(0, lambda: (
                self.progress.set(max(0, min(pct, 100)) / 100),
                self.status_lbl.configure(text=msg),
            ))

        def _work():
            try:
                result = self.api.compare_pricelist(
                    self._pl_path, segments=segs, threshold=threshold,
                    progress_cb=_prog,
                )
            except Exception as e:
                self.after(0, lambda: self._pl_done(None, str(e)))
                return
            self.after(0, lambda: self._pl_done(result, None))

        threading.Thread(target=_work, daemon=True).start()

    def _pl_done(self, result, error):
        self.progress.grid_remove()
        self.status_lbl.configure(text="")
        self._pl_run_btn.configure(state="normal", text="Сверить цены")

        if error:
            self._pl_summary.configure(text=f"Ошибка: {error}")
            messagebox.showerror("Сверка прейскуранта", error)
            return

        self._pl_result = result
        rows  = result.get("rows", []) or []
        st    = result.get("stats", {}) or {}
        thr   = st.get("threshold_pct", 5)

        self._pl_summary.configure(
            text=(
                f"Кодов в прейскуранте: {st.get('pricelist_codes', 0):,}   |   "
                f"товаров в сегменте: {st.get('products_total', 0):,}   |   "
                f"сопоставлено: {st.get('matched', 0):,}\n"
                f"Отклонение больше {thr:g}%: {st.get('over_threshold', 0):,} "
                f"(выше прейскуранта {st.get('over_higher', 0):,}, "
                f"ниже {st.get('over_lower', 0):,})   |   "
                f"в пределах порога: {st.get('within', 0):,}\n"
                f"Из расхождений с разными единицами измерения: "
                f"{st.get('unit_mismatch', 0):,} — отклонение мнимое, "
                f"сравнивать нельзя (жёлтые строки)."
            ).replace(",", " ")
        )

        self._pl_save_btn.configure(state="normal" if rows else "disabled")

        # Отчёт создаётся сразу рядом с прейскурантом
        if rows:
            self._pl_autosave_report()

    def _pl_autosave_report(self):
        """Формирует отчёт рядом с исходным прейскурантом сразу после сверки."""
        if not self._pl_result or not self._pl_path:
            return
        base = os.path.splitext(os.path.basename(self._pl_path))[0]
        out  = os.path.join(os.path.dirname(self._pl_path) or ".",
                            f"Сверка цен АГСК — {base}.xlsx")

        def _work():
            try:
                from services.pricelist_report import build_report
                build_report(out, self._pl_result.get("rows", []),
                             self._pl_result.get("stats", {}))
            except Exception as e:
                import traceback; traceback.print_exc()
                self.after(0, lambda: self._pl_summary.configure(
                    text=self._pl_summary.cget("text")
                         + f"\n\nОтчёт создать не удалось: {e}"))
                return

            def _ok():
                self._pl_summary.configure(
                    text=self._pl_summary.cget("text")
                         + f"\n\nОтчёт сохранён: {out}")
                if messagebox.askyesno(
                    "Отчёт готов",
                    f"Отчёт сохранён рядом с прейскурантом:\n{out}\n\nОткрыть?",
                ):
                    self._pl_open_file(out)
            self.after(0, _ok)

        threading.Thread(target=_work, daemon=True).start()

    @staticmethod
    def _pl_open_file(path: str):
        """Открывает файл средствами системы."""
        import subprocess, sys as _sys
        try:
            if _sys.platform.startswith("win"):
                os.startfile(path)          # noqa: S606
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showwarning("", f"Не удалось открыть файл: {e}")

    def _pl_save_report(self):
        # После сверки с эксель-базой сохраняем её отчёт, а не отчёт по БД
        if getattr(self, "_pl_sync_result", None):
            path = filedialog.asksaveasfilename(
                title="Сохранить отчёт сверки",
                defaultextension=".xlsx",
                initialfile="Сверка с прейскурантом.xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not path:
                return
            try:
                from services.pricelist_sync_report import build_sync_report
                build_sync_report(
                    path, self._pl_sync_result, self._pl_base_path,
                    os.path.basename(self._pl_path),
                    applied=getattr(self, "_pl_sync_applied", False),
                )
            except Exception as e:
                messagebox.showerror("Ошибка сохранения", str(e), parent=self)
                return
            messagebox.showinfo("Отчёт сохранён", f"Файл: {path}", parent=self)
            return

        if not self._pl_result:
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт сверки",
            defaultextension=".xlsx",
            initialfile="Сверка цен АГСК.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return

        self._pl_save_btn.configure(state="disabled", text="Сохранение...")

        def _work():
            try:
                from services.pricelist_report import build_report
                build_report(path, self._pl_result.get("rows", []),
                             self._pl_result.get("stats", {}))
            except Exception as e:
                import traceback; traceback.print_exc()
                self.after(0, lambda: (
                    messagebox.showerror("Ошибка сохранения", str(e)),
                    self._pl_save_btn.configure(
                        state="normal", text="💾 Сохранить отчёт как..."),
                ))
                return
            self.after(0, lambda: (
                self._pl_save_btn.configure(
                    state="normal", text="💾 Сохранить отчёт как..."),
                messagebox.showinfo("Отчёт сохранён", f"Файл: {path}"),
            ))

        threading.Thread(target=_work, daemon=True).start()

    def _build_logs_tab(self):
        tab = self.tabview.tab(t("db_tab_logs"))
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Log.Treeview", rowheight=26, font=("Calibri", 12))
        style.configure("Log.Treeview.Heading",
                        background=NAVY, foreground="white",
                        font=("Calibri", 12, "bold"))

        cols = ["segment", "action", "before_after", "who", "date", "file"]
        self.log_tree = ttk.Treeview(tab, columns=cols, show="headings",
                                      style="Log.Treeview")
        hdrs = ["Сегмент", "Действие", "До → После", "Кто", "Дата", "Файл"]
        for col, hdr, w in zip(cols, hdrs, [60, 90, 130, 130, 155, 250]):
            self.log_tree.heading(col, text=hdr)
            self.log_tree.column(col, width=w)

        vsb = ttk.Scrollbar(tab, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=vsb.set)
        self.log_tree.grid(row=0, column=0, sticky="nsew", padx=(16, 0), pady=16)
        vsb.grid(row=0, column=1, sticky="ns", pady=16)

        self.load_logs_btn = ctk.CTkButton(
            tab, text=t("db_load_logs"), font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=180, corner_radius=RADIUS_SM,
            command=self._load_logs,
        )
        self.load_logs_btn.grid(row=1, column=0, pady=(0, 12))

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _handle_api_error(self, exc: Exception, context: str = ""):
        """Показывает диалог ошибки. Для SessionExpiredError — предлагает перелогиниться."""
        if isinstance(exc, SessionExpiredError):
            ans = messagebox.askyesno(
                "Сессия истекла",
                "Ваша сессия истекла или прав администратора недостаточно.\n\n"
                "Войти заново?",
                parent=self,
            )
            if ans:
                try:
                    self.app._show_auth()
                except Exception:
                    pass
        else:
            title = f"Ошибка{': ' + context if context else ''}"
            messagebox.showerror(title, str(exc), parent=self)

    def _refresh_count(self):
        def _worker():
            try:
                count = self.api.get_products_count()
                self.after(0, lambda: self.count_lbl.configure(
                    text=t("db_count", count=f"{count:,}")))
            except Exception as e:
                self.after(0, lambda: self.count_lbl.configure(text=f"Ошибка: {e}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _reconnect_pinecone(self):
        """Сбрасывает кеш Pinecone и переподключается с текущими ключами."""
        def _worker():
            try:
                res  = self.api.pinecone_reconnect()
                test = res.get("test", {})
                if test.get("ok"):
                    vecs = test.get("total_vector_count", "?")
                    self.after(0, lambda: messagebox.showinfo(
                        "Pinecone", f"✅ Подключено\nВекторов в индексе: {vecs}"))
                else:
                    err = test.get("error", "неизвестная ошибка")
                    self.after(0, lambda: messagebox.showerror(
                        "Pinecone", f"❌ Ошибка подключения:\n{err}"))
            except Exception as e:
                self.after(0, lambda: self._handle_api_error(e, "Pinecone переподключение"))
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_budget(self):
        """Загружает состояние дневного бюджета векторизации."""
        def _worker():
            try:
                b = self.api.get_embed_budget()
                spent     = b.get("spent_usd", 0.0)
                remaining = b.get("remaining_usd", 0.0)
                budget    = b.get("budget_usd", 1.60)
                segs      = b.get("segments", {})
                seg_parts = "  ".join(
                    f"{s.upper()}: ${v['cost_usd']:.4f}" for s, v in segs.items()
                ) if segs else ""
                color = "#27AE60" if remaining > 0.10 else ("#E67E22" if remaining > 0 else "#E74C3C")
                text  = (f"потрачено ${spent:.4f} / остаток ${remaining:.4f} "
                         f"(лимит ${budget:.2f})"
                         + (f"  │  {seg_parts}" if seg_parts else ""))
                self.after(0, lambda: self._budget_lbl.configure(text=text, text_color=color))
            except Exception as e:
                self.after(0, lambda: self._budget_lbl.configure(
                    text=f"Ошибка: {e}", text_color="#E74C3C"))
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_stats(self):
        """Загружает статистику по сегментам и обновляет _stats_lbl."""
        def _worker():
            try:
                s = self.api.get_db_stats()
                ss  = s.get("ss",  0)
                os_ = s.get("os",  0)
                sil = s.get("sil", 0)
                tot = s.get("total", ss + os_ + sil)
                text = (f"SS: {ss:,}  │  OS: {os_:,}  │  SIL: {sil:,}  │  "
                        f"Всего: {tot:,}")
                self.after(0, lambda: self._stats_lbl.configure(text=text))
            except SessionExpiredError as e:
                self.after(0, lambda: self._handle_api_error(e))
            except Exception as e:
                self.after(0, lambda: self._stats_lbl.configure(text=f"Ошибка: {e}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _clear_segment(self):
        """Очищает выбранный сегмент БД после подтверждения."""
        label = self._clear_seg_var.get()
        try:
            seg_code = self._clear_seg_codes[self._clear_seg_labels.index(label)]
        except (ValueError, IndexError):
            seg_code = "ss"
        seg_map  = {"ss": "Слаботочные (SS)", "os": "Освещение (OS)", "sil": "Силовые (SIL)"}
        seg_name = seg_map.get(seg_code, seg_code.upper())
        ok = messagebox.askyesno(
            "Подтвердите очистку",
            f"⚠  Все товары сегмента\n\n  {seg_name}\n\n"
            f"будут деактивированы.\n"
            f"Восстановить можно только повторным импортом.\n\nПродолжить?",
            parent=self,
        )
        if not ok:
            return

        def _worker():
            try:
                result = self.api.clear_segment(seg_code)
                affected = result.get("affected", "?")
                self.after(0, lambda: (
                    messagebox.showinfo(
                        "Готово",
                        f"Сегмент {seg_name} очищен.\nДеактивировано позиций: {affected}",
                        parent=self,
                    ),
                    self._refresh_count(),
                    self._refresh_stats(),
                ))
            except Exception as e:
                self.after(0, lambda: self._handle_api_error(e, "Очистка сегмента"))

        threading.Thread(target=_worker, daemon=True).start()

    def _import_both(self):
        path = self.db_drop.get_path()
        if not path:
            messagebox.showwarning("", t("db_no_file"))
            return
        # For admins: confirm the target segment before import
        if self._is_admin():
            label = self._import_seg_var.get()
            try:
                seg_code = self._import_seg_codes[self._import_seg_labels.index(label)]
            except (ValueError, IndexError):
                seg_code = "ss"
            seg_map = {"ss": "Слаботочные (SS)", "os": "Освещение (OS)", "sil": "Силовые (SIL)"}
            seg_name = seg_map.get(seg_code, seg_code.upper())
            ok = messagebox.askyesno(
                "Подтвердите импорт",
                f"Файл будет импортирован в сегмент:\n\n  {seg_name}\n\n"
                f"Убедитесь, что выбран правильный сегмент!\nПродолжить?",
                parent=self,
            )
            if not ok:
                return
        self._run_import_both(path, "")

    def _run_import_both(self, path: str, pwd: str):
        self._anim_token = getattr(self, "_anim_token", 0) + 1
        token = self._anim_token

        self.progress.grid()
        self.progress.set(0)
        self._animate(0, token)
        self.status_lbl.configure(text=t("db_running"), text_color=TEXT_SECONDARY)
        self.db_btn.configure(state="disabled")

        def _worker():
            results = {}
            errors  = []
            expired = []
            # Для администраторов — берём выбранный сегмент; для менеджеров — их сегмент
            if self._is_admin():
                label = self._import_seg_var.get()
                try:
                    seg = self._import_seg_codes[self._import_seg_labels.index(label)]
                except (ValueError, IndexError):
                    seg = "ss"
            else:
                seg = getattr(self.app.config, "user_segment", "ss")
            try:
                results["db"] = self.api.import_products(path, pwd, segment=seg)
            except SessionExpiredError as e:
                expired.append(e)
            except Exception as e:
                errors.append(f"БД: {e}")
            if not expired:
                try:
                    results["const"] = self.api.import_constants(path, pwd)
                except SessionExpiredError as e:
                    expired.append(e)
                except Exception as e:
                    errors.append(f"Константы: {e}")

            # Истёкшая сессия — не ошибка импорта, а повод перелогиниться
            if expired:
                self.after(0, lambda e=expired[0]: self._session_expired_during_import(e))
            else:
                self.after(0, lambda: self._done_both(results, errors))

        threading.Thread(target=_worker, daemon=True).start()

    def _session_expired_during_import(self, exc: Exception):
        """Импорт прерван из-за сессии: снимаем прогресс и зовём общий диалог."""
        self._anim_token = getattr(self, "_anim_token", 0) + 1
        self.progress.set(0)
        self.progress.grid_remove()
        self.db_btn.configure(state="normal")
        self.status_lbl.configure(text="❌  Сессия истекла — импорт не выполнен",
                                  text_color="#E74C3C")
        self._handle_api_error(exc, "импорт базы")

    def _animate(self, val, token: int):
        if token != getattr(self, "_anim_token", 0):
            return
        if val < 0.85:
            nxt = val + 0.015
            self.progress.set(nxt)
            self.after(100, lambda: self._animate(nxt, token))

    def _done_both(self, results: dict, errors: list):
        self._anim_token = getattr(self, "_anim_token", 0) + 1
        self.progress.set(1.0)
        self.db_btn.configure(state="normal")
        self._refresh_count()
        if self._is_admin():
            self._refresh_stats()
        # Всегда обновляем бренды после импорта (видно всем ролям)
        self._load_brand_stats()

        if errors:
            self.status_lbl.configure(
                text="❌  " + "  |  ".join(errors), text_color="#E74C3C")
            messagebox.showerror("", "\n".join(errors))
        else:
            db_r    = results.get("db", {})
            const_r = results.get("const", {})
            added   = db_r.get("added", 0)
            updated = db_r.get("updated", 0)
            brands  = const_r.get("brands_updated", 0)
            msg = t("db_import_ok", added=added, updated=updated)
            if brands:
                msg += f"\nКонстанты: обновлено брендов — {brands}"
            self.status_lbl.configure(
                text=f"✅  {msg.split(chr(10))[0]}", text_color="#27AE60")
            messagebox.showinfo("OK", msg)

    def _start_vectorization(self):
        """Запускает переиндексацию Pinecone.
        Администратор выбирает сегмент через _vec_seg_btn (включая «Все сегменты»).
        Менеджеры не имеют доступа к этой функции.
        """
        if self._is_admin():
            label = self._vec_seg_var.get()
            try:
                seg = self._vec_seg_codes[self._vec_seg_labels.index(label)]
            except (ValueError, IndexError):
                seg = "all"
            seg_display = "все сегменты" if seg == "all" else label
        else:
            # Менеджеры не должны попадать сюда — кнопка скрыта
            return

        def _worker():
            try:
                result = self.api.start_vectorization(segment=seg)
                budget = result.get("budget", {})
                spent  = budget.get("spent_usd", 0.0)
                rem    = budget.get("remaining_usd", 0.0)
                base_msg = result.get("message", f"Векторизация ({seg_display}) запущена")
                msg = (f"{base_msg}\n\n"
                       f"Бюджет: потрачено ${spent:.4f}, остаток ${rem:.4f}")
                self.after(0, lambda: (
                    messagebox.showinfo("Векторизация", msg),
                    self._refresh_budget(),
                ))
            except Exception as e:
                self.after(0, lambda: self._handle_api_error(e, "Векторизация"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Brands tab logic ──────────────────────────────────────────────────────

    def _load_brand_stats(self):
        """Загружает статистику по брендам с сервера."""
        def _worker():
            try:
                data = self.api.get_brand_stats()
                self.after(0, lambda: self._populate_brand_tree(data))
            except SessionExpiredError as e:
                self.after(0, lambda: self._handle_api_error(e))
            except Exception as e:
                self.after(0, lambda: self._brand_summary_lbl.configure(
                    text=f"Ошибка загрузки: {e}", text_color="#E74C3C"))
        threading.Thread(target=_worker, daemon=True).start()

    def _populate_brand_tree(self, data: list):
        """Обогащает данные дельтами и перерисовывает таблицу."""
        old_prev = dict(self._prev_brand_stats)
        has_prev = bool(old_prev)

        enriched = []
        for d in data:
            brand = (d.get("brand") or "").strip()
            if not brand:
                continue
            total = d.get("total", 0) or 0
            prev  = old_prev.get(brand)

            if prev is None:
                if has_prev:
                    delta_val, delta_str, tag = total, f"+{total:,}", "new_brand"
                else:
                    delta_val, delta_str, tag = 0, "—", ""
            else:
                diff = total - prev
                if diff > 0:
                    delta_val, delta_str, tag = diff, f"+{diff:,}", "increased"
                elif diff < 0:
                    delta_val, delta_str, tag = diff, f"−{abs(diff):,}", "decreased"
                else:
                    delta_val, delta_str, tag = 0, "—", ""

            enriched.append({
                **d,
                "brand":       brand,
                "_delta_val":  delta_val,
                "_delta_str":  delta_str,
                "_tag":        tag,
            })

        # Бренды, которые полностью исчезли
        current = {e["brand"] for e in enriched}
        for brand, prev_total in old_prev.items():
            if brand not in current and prev_total > 0:
                enriched.append({
                    "brand": brand, "ss": 0, "os": 0, "sil": 0, "total": 0,
                    "_delta_val": -prev_total,
                    "_delta_str": f"−{prev_total:,}",
                    "_tag":       "removed",
                })

        self._brand_data = enriched
        self._apply_brand_sort()          # сортирует и вызывает _filter_brands

        # Обновляем предыдущее состояние для следующего обновления
        self._prev_brand_stats = {
            (d.get("brand") or ""): (d.get("total") or 0) for d in data
        }

        n_brands    = len(data)
        n_positions = sum(d.get("total", 0) or 0 for d in data)
        n_changed   = sum(
            1 for e in enriched
            if e.get("_tag") in ("increased", "decreased", "new_brand", "removed")
        )
        suffix = f"  │  ✏ изменений: {n_changed}" if n_changed else ""
        self._brand_summary_lbl.configure(
            text=f"Брендов: {n_brands}  │  Позиций: {n_positions:,}{suffix}",
            text_color=TEXT_SECONDARY,
        )

    def _filter_brands(self):
        """Фильтрует таблицу по введённому тексту (без повторного запроса к серверу)."""
        q = ""
        try:
            q = self._brand_search_var.get().strip().lower()
        except Exception:
            pass
        self._brand_tree.delete(*self._brand_tree.get_children())
        for d in self._brand_data:
            brand = d.get("brand", "")
            if q and q not in brand.lower():
                continue
            ss    = d.get("ss",    0) or 0
            os_   = d.get("os",    0) or 0
            sil   = d.get("sil",   0) or 0
            total = d.get("total", 0) or 0
            self._brand_tree.insert(
                "", "end",
                values=(
                    brand,
                    f"{ss:,}"    if ss    else "—",
                    f"{os_:,}"   if os_   else "—",
                    f"{sil:,}"   if sil   else "—",
                    f"{total:,}" if total else "—",
                    d.get("_delta_str", "—"),
                ),
                tags=(d.get("_tag", ""),) if d.get("_tag") else (),
            )

    def _sort_brands(self, col: str):
        """Переключает сортировку по нажатой колонке."""
        if self._brand_sort_col == col:
            self._brand_sort_asc = not self._brand_sort_asc
        else:
            self._brand_sort_col = col
            self._brand_sort_asc = col == "brand"  # бренды — по возрастанию по умолчанию
        self._apply_brand_sort()

    def _apply_brand_sort(self):
        """Сортирует _brand_data и вызывает _filter_brands."""
        col = self._brand_sort_col
        asc = self._brand_sort_asc

        _num_cols = {"ss", "os", "sil", "total", "_delta_val"}

        def _key(d):
            if col == "brand":
                return (d.get("brand") or "").lower()
            if col == "delta":
                return d.get("_delta_val", 0)
            return d.get(col, 0) or 0

        self._brand_data.sort(key=_key, reverse=not asc)

        # Обновляем заголовки (стрелочки)
        arrow = " ▲" if asc else " ▼"
        for c in ["brand", "ss", "os", "sil", "total", "delta"]:
            hdr_base = {
                "brand": "Бренд", "ss": "SS", "os": "OS",
                "sil": "SIL", "total": "Всего", "delta": "Δ изменение",
            }[c]
            self._brand_tree.heading(c, text=hdr_base + (arrow if c == col else ""))

        self._filter_brands()

    def _on_tab_change(self):
        """Вызывается при переключении вкладки tabview."""
        try:
            tab_name = self.tabview.get()
            if t("db_tab_logs") in tab_name and not self.log_tree.get_children():
                self._load_logs()
            elif "Бренды" in tab_name and not self._brand_data:
                self._load_brand_stats()
        except Exception:
            pass

    def _load_logs(self):
        _action_map = {
            "import":      "импорт",
            "clear":       "очистка",
            "hard_delete": "удаление",
            "vectorize":   "векторизация",
        }
        try:
            logs = self.api.get_logs()
            self.log_tree.delete(*self.log_tree.get_children())
            for log in logs:
                status     = log.get("status", "")
                seg        = (log.get("segment") or "").upper() or "—"
                action_raw = log.get("action") or "import"
                action     = _action_map.get(action_raw, action_raw)
                cb         = log.get("count_before")
                ca         = log.get("count_after")
                before_after = (f"{cb:,} → {ca:,}" if cb is not None and ca is not None
                                else "—")
                who  = log.get("changed_by") or "—"
                date = str(log.get("created_at", ""))[:19]
                fname = log.get("filename", "")
                vals = (seg, action, before_after, who, date, fname)
                tag = "ok" if status == "success" else "err"
                self.log_tree.insert("", "end", values=vals, tags=(tag,))
            self.log_tree.tag_configure("ok",  background="#D4EDDA")
            self.log_tree.tag_configure("err", background="#F8D7DA")
        except Exception as e:
            messagebox.showerror("", str(e))

    def refresh_lang(self):
        self.title_lbl.configure(text=t("db_title"))
        self.count_lbl.configure(text=t("db_count", count="..."))
        self.refresh_btn.configure(text=t("db_refresh"))
        self.db_desc.configure(text=t("db_import_both_desc"))
        self.db_btn.configure(text=t("db_import_both_btn"))
        self.db_drop.refresh_lang()
        self.load_logs_btn.configure(text=t("db_load_logs"))
        # Обновить подписи сегментного переключателя
        new_labels = [t("seg_ss"), t("seg_os"), t("seg_sil")]
        self._import_seg_labels = new_labels
        self._import_seg_btn.configure(values=new_labels)
        self._import_seg_var.set(new_labels[0])
        self._apply_role_visibility()
