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
    """Карточка drag-and-drop для файлов"""
    def __init__(self, parent, label_key: str, **kwargs):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_LG,
                         border_width=2, border_color="#AEB6BF", **kwargs)
        self.label_key = label_key
        self._path     = None

        self.lbl = ctk.CTkLabel(self,
                                 text=f"📂  {t(label_key)}\n\nПеретащите .xlsx или нажмите для выбора",
                                 font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                 wraplength=380)
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

    def _build(self):
        pad = PAD_MD

        # Заголовок + счётчик
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

        # Вкладки
        self.tabview = ctk.CTkTabview(self, fg_color=BG_CARD,
                                       corner_radius=RADIUS_MD,
                                       segmented_button_fg_color=NAVY,
                                       segmented_button_selected_color=NAVY_LIGHT,
                                       segmented_button_unselected_color=BLUE_MID,
                                       segmented_button_selected_hover_color=BLUE_LIGHT,
                                       text_color="white",
                                       text_color_disabled=TEXT_NAV)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, pad))

        self.tabview.add(t("db_tab_import"))
        self.tabview.add(t("db_tab_const"))
        self.tabview.add(t("db_tab_logs"))

        self._build_import_tab()
        self._build_const_tab()
        self._build_logs_tab()

        # Статус прогресса (общий)
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

        self.db_desc = ctk.CTkLabel(tab, text=t("db_import_desc"),
                                     font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                     wraplength=600, anchor="w")
        self.db_desc.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        self.db_drop = DropCard(tab, "db_drop_label")
        self.db_drop.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        self._build_password_row(tab, "db", row=2)

        self.db_btn = ctk.CTkButton(
            tab, text=t("db_import_btn"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=44, corner_radius=RADIUS_MD,
            command=self._import_db
        )
        self.db_btn.grid(row=3, column=0, padx=16, pady=(8, 0), sticky="ew")

    def _build_const_tab(self):
        tab = self.tabview.tab(t("db_tab_const"))
        tab.grid_columnconfigure(0, weight=1)

        self.const_desc = ctk.CTkLabel(tab, text=t("db_const_desc"),
                                        font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                        wraplength=600, anchor="w")
        self.const_desc.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        self.const_drop = DropCard(tab, "db_const_label")
        self.const_drop.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        self._build_password_row(tab, "const", row=2)

        self.const_btn = ctk.CTkButton(
            tab, text=t("db_const_btn"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=44, corner_radius=RADIUS_MD,
            command=self._import_const
        )
        self.const_btn.grid(row=3, column=0, padx=16, pady=(8, 0), sticky="ew")

    def _build_password_row(self, parent, prefix: str, row: int):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, padx=16, sticky="ew")
        lbl_attr = f"{prefix}_pwd_lbl"
        ent_attr = f"{prefix}_pwd_entry"

        lbl = ctk.CTkLabel(frame, text=t("db_password"), font=FONT_NORMAL,
                            text_color=NAVY, anchor="w")
        lbl.pack(side="left")
        setattr(self, lbl_attr, lbl)

        entry = ctk.CTkEntry(frame, placeholder_text=t("db_password_ph"),
                              show="•", width=260, height=36, font=FONT_NORMAL)
        entry.pack(side="left", padx=(12, 0))
        setattr(self, ent_attr, entry)

    def _build_logs_tab(self):
        tab = self.tabview.tab(t("db_tab_logs"))
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Log.Treeview", rowheight=26, font=("Calibri", 12))
        style.configure("Log.Treeview.Heading",
                        background=NAVY, foreground="white",
                        font=("Calibri", 12, "bold"))

        cols = ["file", "added", "updated", "status", "date"]
        self.log_tree = ttk.Treeview(tab, columns=cols, show="headings",
                                      style="Log.Treeview")
        hdrs = [t("db_log_file"), t("db_log_added"), t("db_log_updated"),
                t("db_log_status"), t("db_log_date")]
        for col, hdr, w in zip(cols, hdrs, [280, 90, 90, 100, 180]):
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
            command=self._load_logs
        )
        self.load_logs_btn.grid(row=1, column=0, pady=(0, 12))

    # ── Логика ───────────────────────────────────────────────────────────────
    def _refresh_count(self):
        def _worker():
            try:
                count = self.api.get_products_count()
                self.after(0, lambda: self.count_lbl.configure(
                    text=t("db_count", count=f"{count:,}")))
            except Exception as e:
                self.after(0, lambda: self.count_lbl.configure(text=f"Ошибка: {e}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _get_password(self, prefix: str) -> str:
        return getattr(self, f"{prefix}_pwd_entry").get().strip()

    def _import_db(self):
        path = self.db_drop.get_path()
        if not path:
            messagebox.showwarning("", t("db_no_file"))
            return
        pwd = self._get_password("db")
        if not pwd:
            messagebox.showwarning("", t("db_password"))
            return
        self._run_import(self.api.import_products, path, pwd)

    def _import_const(self):
        path = self.const_drop.get_path()
        if not path:
            messagebox.showwarning("", t("db_no_file"))
            return
        pwd = self._get_password("const")
        if not pwd:
            messagebox.showwarning("", t("db_password"))
            return
        self._run_import(self.api.import_constants, path, pwd)

    def _run_import(self, func, path: str, pwd: str):
        self.progress.grid()
        self.progress.set(0)
        self._animate(0)
        self.status_lbl.configure(text=t("db_running"), text_color=TEXT_SECONDARY)
        self.db_btn.configure(state="disabled")
        self.const_btn.configure(state="disabled")

        def _worker():
            try:
                result = func(path, pwd)
                self.after(0, lambda: self._done(result))
            except Exception as e:
                self.after(0, lambda: self._error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _animate(self, val):
        if val < 0.85:
            self.progress.set(val + 0.015)
            self.after(100, lambda: self._animate(val + 0.015))

    def _done(self, result: dict):
        self.progress.set(1.0)
        added   = result.get("added",   result.get("brands_updated", 0))
        updated = result.get("updated", 0)
        self.status_lbl.configure(
            text=f"✅  {t('db_import_ok', added=added, updated=updated).split(chr(10))[0]}",
            text_color="#27AE60"
        )
        self.db_btn.configure(state="normal")
        self.const_btn.configure(state="normal")
        self._refresh_count()
        messagebox.showinfo("OK", t("db_import_ok", added=added, updated=updated))

    def _error(self, error: str):
        self.progress.grid_remove()
        self.status_lbl.configure(text=f"❌  {error}", text_color="#E74C3C")
        self.db_btn.configure(state="normal")
        self.const_btn.configure(state="normal")
        messagebox.showerror("", t("db_import_error", error=error))

    def _load_logs(self):
        try:
            logs = self.api.get_logs()
            self.log_tree.delete(*self.log_tree.get_children())
            for log in logs:
                status = log.get("status", "")
                vals = (
                    log.get("filename",""),
                    log.get("rows_added", 0),
                    log.get("rows_updated", 0),
                    "✅ ok" if status == "success" else f"❌ {status}",
                    str(log.get("created_at",""))[:19]
                )
                tag = "ok" if status == "success" else "err"
                self.log_tree.insert("", "end", values=vals, tags=(tag,))
            self.log_tree.tag_configure("ok",  background="#D4EDDA")
            self.log_tree.tag_configure("err", background="#F8D7DA")
        except Exception as e:
            messagebox.showerror("", str(e))

    def refresh_lang(self):
        self.title_lbl.configure(text=t("db_title"))
        self.refresh_btn.configure(text=t("db_refresh"))
        self.db_desc.configure(text=t("db_import_desc"))
        self.const_desc.configure(text=t("db_const_desc"))
        self.db_btn.configure(text=t("db_import_btn"))
        self.const_btn.configure(text=t("db_const_btn"))
        self.db_drop.refresh_lang()
        self.const_drop.refresh_lang()
        self.load_logs_btn.configure(text=t("db_load_logs"))
        self.db_pwd_lbl.configure(text=t("db_password"))
        self.const_pwd_lbl.configure(text=t("db_password"))
        count_text = self.count_lbl.cget("text")
        self.count_lbl.configure(text=t("db_count", count=count_text.split(":")[-1].strip()))
        self.db_drop.refresh_lang()
        self.const_drop.refresh_lang()
        self.load_logs_btn.configure(text=t("db_load_logs"))
        self.db_pwd_lbl.configure(text=t("db_password"))
        self.const_pwd_lbl.configure(text=t("db_password"))
        count_text = self.count_lbl.cget("text")
        self.count_lbl.configure(text=t("db_count", count=count_text.split(":")[-1].strip()))
