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


class UploadPage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api   = api
        self.app   = app
        self._path = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build()

    # ── Main layout: tabview ────────────────────────────────────────────────

    def _build(self):
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=BG_MAIN, corner_radius=0,
            segmented_button_fg_color=NAVY,
            segmented_button_selected_color=NAVY_LIGHT,
            segmented_button_unselected_color=BLUE_MID,
            segmented_button_selected_hover_color=BLUE_LIGHT,
            text_color="white", text_color_disabled=TEXT_NAV,
        )
        self.tabview.grid(row=0, column=0, sticky="nsew")
        self.tabview.add(t("upload_tab_upload"))
        self.tabview.add(t("upload_tab_history"))
        self._build_upload_tab()
        self._build_history_tab()

    # ── Upload tab ──────────────────────────────────────────────────────────

    def _build_upload_tab(self):
        tab = self.tabview.tab(t("upload_tab_upload"))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)
        pad = PAD_XL

        self.title_lbl = ctk.CTkLabel(tab, text=t("upload_title"),
                                       font=FONT_TITLE, text_color=NAVY, anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 4))

        self.desc_lbl = ctk.CTkLabel(tab, text=t("upload_desc"),
                                      font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                      anchor="w", wraplength=700)
        self.desc_lbl.grid(row=1, column=0, sticky="w", padx=pad, pady=(0, PAD_MD))

        self.drop_zone = ctk.CTkFrame(
            tab, fg_color=BG_CARD,
            corner_radius=RADIUS_LG, border_width=2, border_color="#AEB6BF"
        )
        self.drop_zone.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, PAD_MD))
        self.drop_zone.grid_columnconfigure(0, weight=1)

        self.drop_icon = ctk.CTkLabel(self.drop_zone, text="📄",
                                       font=("Segoe UI Emoji", 52))
        self.drop_icon.grid(row=0, pady=(32, 8))

        self.drop_title = ctk.CTkLabel(self.drop_zone, text=t("upload_drop_title"),
                                        font=FONT_HEADING, text_color=NAVY)
        self.drop_title.grid(row=1)

        self.drop_sub = ctk.CTkLabel(self.drop_zone, text=t("upload_drop_sub"),
                                      font=FONT_NORMAL, text_color=TEXT_SECONDARY)
        self.drop_sub.grid(row=2, pady=(4, 32))

        self._bind_dnd()

        self.browse_btn = ctk.CTkButton(
            tab, text=t("upload_browse"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=44, corner_radius=RADIUS_MD, width=220,
            command=self._browse
        )
        self.browse_btn.grid(row=3, pady=4)

        self.file_lbl = ctk.CTkLabel(tab, text=t("upload_no_file"),
                                      font=FONT_NORMAL, text_color=TEXT_SECONDARY)
        self.file_lbl.grid(row=4, pady=(0, 8))

        self.progress = ctk.CTkProgressBar(tab, width=500,
                                            progress_color=NAVY_LIGHT,
                                            fg_color="#D5D8DC")
        self.progress.set(0)
        self.progress.grid(row=5, pady=(0, 4))
        self.progress.grid_remove()

        self.progress_lbl = ctk.CTkLabel(tab, text="", font=FONT_SMALL,
                                          text_color=TEXT_SECONDARY)
        self.progress_lbl.grid(row=6)
        self.progress_lbl.grid_remove()

        self.send_btn = ctk.CTkButton(
            tab, text=t("upload_send"),
            font=(*FONT_HEADING[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=52, corner_radius=RADIUS_MD, width=320,
            state="disabled",
            command=self._send
        )
        self.send_btn.grid(row=7, pady=(12, pad))

    # ── History tab ─────────────────────────────────────────────────────────

    def _build_history_tab(self):
        tab = self.tabview.tab(t("upload_tab_history"))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Top bar
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=PAD_MD, pady=(PAD_MD, 6))
        top.grid_columnconfigure(0, weight=1)

        self.hist_title_lbl = ctk.CTkLabel(
            top, text=t("upload_tab_history"),
            font=FONT_TITLE, text_color=NAVY, anchor="w"
        )
        self.hist_title_lbl.grid(row=0, column=0, sticky="w")

        self.hist_refresh_btn = ctk.CTkButton(
            top, text=t("upload_hist_refresh"),
            font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=140, corner_radius=RADIUS_SM,
            command=self._load_history,
        )
        self.hist_refresh_btn.grid(row=0, column=1)

        # Treeview
        style = ttk.Style()
        style.configure("Hist.Treeview",
                        rowheight=30, font=("Calibri", 12),
                        background=BG_CARD, fieldbackground=BG_CARD)
        style.configure("Hist.Treeview.Heading",
                        background=NAVY, foreground="white",
                        font=("Calibri", 12, "bold"))
        style.map("Hist.Treeview", background=[("selected", BLUE_MID)])

        cols = ["who", "file", "project", "date"]
        self.hist_tree = ttk.Treeview(tab, columns=cols, show="headings",
                                       style="Hist.Treeview")

        col_widths = {"who": 180, "file": 220, "project": 420, "date": 150}
        col_keys   = {"who": "upload_hist_who", "file": "upload_hist_file",
                      "project": "upload_hist_project", "date": "upload_hist_date"}
        for col in cols:
            self.hist_tree.heading(col, text=t(col_keys[col]))
            self.hist_tree.column(col, width=col_widths[col], minwidth=80)

        vsb = ttk.Scrollbar(tab, orient="vertical", command=self.hist_tree.yview)
        hsb = ttk.Scrollbar(tab, orient="horizontal", command=self.hist_tree.xview)
        self.hist_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.hist_tree.grid(row=1, column=0, sticky="nsew",
                             padx=(PAD_MD, 0), pady=(0, 0))
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="ew", padx=(PAD_MD, 0))

        self.hist_status_lbl = ctk.CTkLabel(
            tab, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self.hist_status_lbl.grid(row=3, column=0, pady=(4, PAD_SM))

        # Load on first show
        self.after(500, self._load_history)

    def _load_history(self):
        self.hist_refresh_btn.configure(state="disabled")
        self.hist_status_lbl.configure(text="...")

        def _worker():
            try:
                rows = self.api.get_pdf_history()
                self.after(0, lambda: self._populate_history(rows))
            except Exception as e:
                self.after(0, lambda: self._history_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_history(self, rows: list):
        self.hist_tree.delete(*self.hist_tree.get_children())
        for r in rows:
            self.hist_tree.insert("", "end", values=(
                r.get("full_name", "—"),
                r.get("filename",  "—"),
                r.get("project_name", "—"),
                r.get("uploaded_at", "—"),
            ))
        count = len(rows)
        self.hist_status_lbl.configure(
            text=f"{count} " + ("записей" if count != 1 else "запись"),
            text_color=TEXT_SECONDARY
        )
        self.hist_refresh_btn.configure(state="normal")

    def _history_error(self, error: str):
        self.hist_status_lbl.configure(
            text=t("upload_hist_error") + f": {error}", text_color="#E74C3C"
        )
        self.hist_refresh_btn.configure(state="normal")

    # ── DnD / browse ────────────────────────────────────────────────────────

    def _bind_dnd(self):
        targets = [self.drop_zone, self.drop_icon, self.drop_title, self.drop_sub]
        for w in targets:
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
                w.configure(cursor="hand2")
            except Exception as e:
                print(f"[DnD] {w}: {e}")

    def _on_drop(self, event):
        raw = (event.data or "").strip()
        if raw.startswith("{"):
            end = raw.find("}")
            path = raw[1:end] if end > 0 else raw.strip("{}")
        else:
            path = raw.split()[0] if raw else ""
        if path.lower().endswith(".pdf"):
            self._set_file(path)
        else:
            messagebox.showwarning("", t("upload_wrong_type"))

    def _browse(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF", "*.pdf"), ("All", "*.*")]
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._path = path
        name = os.path.basename(path)
        self.file_lbl.configure(text=f"📄  {name}", text_color=NAVY)
        self.drop_zone.configure(border_color=NAVY_LIGHT, fg_color=BLUE_PALE)
        self.send_btn.configure(state="normal")

    # ── Send ────────────────────────────────────────────────────────────────

    def _send(self):
        if not self._path:
            return
        self.send_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        self.progress.set(0)
        self.progress.grid()
        self.progress_lbl.grid()
        self._animate_progress(0)

        def _worker():
            try:
                def cb(pct, stage):
                    self.after(0, lambda: self._on_progress(pct, stage))
                result = self.api.parse_pdf(self._path, cb)
                self.after(0, lambda: self._on_done(result))
            except Exception as e:
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _animate_progress(self, val: float):
        if val < 0.85:
            self.progress.set(val + 0.01)
            self.after(120, lambda: self._animate_progress(val + 0.01))

    def _on_progress(self, pct: int, stage: str):
        self.progress.set(pct / 100)
        self.progress_lbl.configure(text=t(f"upload_{stage}", default=stage))

    def _on_done(self, result: dict):
        self.progress.set(1.0)
        total = result.get("total", 0)
        self.progress_lbl.configure(
            text=t("upload_done") + str(total), text_color=NAVY_LIGHT
        )
        self.send_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        self.app.on_result_ready(result)
        # Refresh history in background so new entry appears
        self.after(1000, self._load_history)

    def _on_error(self, error: str):
        self.progress.grid_remove()
        self.progress_lbl.grid_remove()
        self.send_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        messagebox.showerror(t("upload_error_title"), t("upload_error_msg") + error)

    # ── Reset / lang ─────────────────────────────────────────────────────────

    def reset(self):
        self._path = None
        self.send_btn.configure(state="disabled")
        self.file_lbl.configure(text=t("upload_no_file"), text_color=TEXT_SECONDARY)
        self.drop_zone.configure(border_color="#AEB6BF", fg_color=BG_CARD)
        self.progress.set(0)
        self.progress.grid_remove()
        self.progress_lbl.grid_remove()

    def refresh_lang(self):
        self.title_lbl.configure(text=t("upload_title"))
        self.desc_lbl.configure(text=t("upload_desc"))
        self.drop_title.configure(text=t("upload_drop_title"))
        self.drop_sub.configure(text=t("upload_drop_sub"))
        self.browse_btn.configure(text=t("upload_browse"))
        self.send_btn.configure(text=t("upload_send"))
        self.hist_title_lbl.configure(text=t("upload_tab_history"))
        self.hist_refresh_btn.configure(text=t("upload_hist_refresh"))
        for col, key in [("who",     "upload_hist_who"),
                         ("file",    "upload_hist_file"),
                         ("project", "upload_hist_project"),
                         ("date",    "upload_hist_date")]:
            self.hist_tree.heading(col, text=t(key))
        if not self._path:
            self.file_lbl.configure(text=t("upload_no_file"))
