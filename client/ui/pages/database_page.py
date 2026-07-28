import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import threading, os

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService

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
            self._seg_info_lbl.grid_remove()
            self._refresh_stats()
            self._refresh_budget()
        else:
            # Менеджер: только импорт в свой сегмент, векторизация скрыта
            self._seg_frame.grid_remove()
            self._vec_frame.grid_remove()
            self._stats_frame.grid_remove()
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
        else:
            self._seg_frame.grid_remove()
            self._vec_frame.grid_remove()
            self._stats_frame.grid_remove()

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
        self.tabview.add(t("db_tab_logs"))

        self._build_import_tab()
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
        tab = self.tabview.tab(t("db_tab_import"))
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

        # Привязываем Configure чтобы CTkTabview не «поднимал» скрытые фреймы при
        # перемещении или изменении размера окна
        tab.bind("<Configure>", self._enforce_role_layout, add="+")

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
                self.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
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
                self.after(0, lambda: messagebox.showerror("Ошибка", str(e), parent=self))

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
            except Exception as e:
                errors.append(f"БД: {e}")
            try:
                results["const"] = self.api.import_constants(path, pwd)
            except Exception as e:
                errors.append(f"Константы: {e}")

            self.after(0, lambda: self._done_both(results, errors))

        threading.Thread(target=_worker, daemon=True).start()

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
                self.after(0, lambda: messagebox.showerror("Ошибка векторизации", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_tab_change(self):
        """Вызывается при переключении вкладки tabview."""
        try:
            tab_name = self.tabview.get()
            if t("db_tab_logs") in tab_name and not self.log_tree.get_children():
                self._load_logs()
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
