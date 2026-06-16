"""
TemplatePage — управление Excel-шаблоном (.xlsm).

Доступна пользователям с ролью administrator или superadmin.
Позволяет:
  • Просматривать информацию о текущем шаблоне (из БД или файловой системы)
  • Загружать новый шаблон (.xlsm) на сервер
  • Скачивать текущий шаблон из БД
"""
import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService


def _fmt_size(n: int) -> str:
    """Human-readable file size."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _fmt_date(iso: str) -> str:
    """Format ISO datetime to readable string."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso


class TemplatePage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api  = api
        self.app  = app
        self._selected_file: str = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, height=72)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_propagate(False)

        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="nsew", padx=32, pady=12)
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_rowconfigure(1, weight=1)

        self._title_lbl = ctk.CTkLabel(
            inner, text=t("tpl_title"),
            font=FONT_TITLE, text_color="white", anchor="w",
        )
        self._title_lbl.grid(row=0, column=0, sticky="w")

        self._subtitle_lbl = ctk.CTkLabel(
            inner, text=t("tpl_subtitle"),
            font=FONT_SMALL, text_color=TEXT_NAV_LIGHT, anchor="w",
            wraplength=900,
        )
        self._subtitle_lbl.grid(row=1, column=0, sticky="w")

    # ── Body ──────────────────────────────────────────────────────────────────

    def _build_body(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_MAIN, corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_columnconfigure(1, weight=1)

        # Left column — current template info
        self._info_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_LG)
        self._info_card.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=24)
        self._info_card.grid_columnconfigure(0, weight=1)
        self._build_info_panel(self._info_card)

        # Right column — upload new template
        upload_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_LG)
        upload_card.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)
        upload_card.grid_columnconfigure(0, weight=1)
        self._build_upload_panel(upload_card)

    # ── Info panel ────────────────────────────────────────────────────────────

    def _build_info_panel(self, parent):
        # Section header
        hdr = ctk.CTkFrame(parent, fg_color=NAVY_DARK, corner_radius=RADIUS_SM)
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 0))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text=t("tpl_current_header"),
            font=(*FONT_NORMAL[:2], "bold"), text_color="white", anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=10)

        # Version badge — shown in header once data is loaded
        self._version_badge = ctk.CTkLabel(
            hdr, text="", font=FONT_SMALL,
            fg_color=BLUE_MID, text_color="white",
            corner_radius=8, padx=8, pady=2,
        )
        self._version_badge.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="e")

        refresh_btn = ctk.CTkButton(
            hdr, text=t("tpl_refresh"), font=FONT_SMALL,
            fg_color=BLUE_MID, hover_color=NAVY, width=120,
            command=self._load_info,
        )
        refresh_btn.grid(row=0, column=2, padx=10, pady=8)

        # Status / source badge
        self._source_lbl = ctk.CTkLabel(
            parent, text="", font=FONT_NORMAL,
            text_color=TEXT_PRIMARY, anchor="w", wraplength=360,
        )
        self._source_lbl.grid(row=1, column=0, sticky="w", padx=24, pady=(14, 4))

        # Info lines
        self._info_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._info_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=4)
        self._info_frame.grid_columnconfigure(1, weight=1)

        self._info_labels = {}
        for i, key in enumerate(["tpl_version", "tpl_filename", "tpl_size",
                                  "tpl_uploaded_by", "tpl_uploaded_at", "tpl_description"]):
            lbl = ctk.CTkLabel(
                self._info_frame, text="", font=FONT_NORMAL,
                text_color=TEXT_PRIMARY, anchor="w", wraplength=300,
            )
            lbl.grid(row=i, column=0, columnspan=2, sticky="w", pady=2)
            self._info_labels[key] = lbl

        # Download button
        self._dl_btn = ctk.CTkButton(
            parent, text=t("tpl_download_btn"), font=FONT_NORMAL,
            fg_color=BLUE_MID, hover_color=NAVY, height=38,
            command=self._download_template,
        )
        self._dl_btn.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 20))
        self._dl_btn.configure(state="disabled")

        # Initial state — show loading
        self._source_lbl.configure(text=t("tpl_loading"))

    # ── Upload panel ──────────────────────────────────────────────────────────

    def _build_upload_panel(self, parent):
        hdr = ctk.CTkFrame(parent, fg_color=NAVY_DARK, corner_radius=RADIUS_SM)
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 0))

        ctk.CTkLabel(
            hdr, text=t("tpl_upload_header"),
            font=(*FONT_NORMAL[:2], "bold"), text_color="white", anchor="w",
        ).pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(
            parent, text=t("tpl_upload_desc"),
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
            anchor="w", wraplength=380,
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(14, 8))

        # File chooser row
        file_row = ctk.CTkFrame(parent, fg_color="transparent")
        file_row.grid(row=2, column=0, sticky="ew", padx=24, pady=4)
        file_row.grid_columnconfigure(1, weight=1)

        browse_btn = ctk.CTkButton(
            file_row, text=t("tpl_browse"), font=FONT_NORMAL,
            fg_color=NAVY, hover_color=NAVY_DARK, width=180,
            command=self._browse_file,
        )
        browse_btn.grid(row=0, column=0, padx=(0, 10))

        self._file_lbl = ctk.CTkLabel(
            file_row, text=t("tpl_no_file"),
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
            anchor="w", wraplength=200,
        )
        self._file_lbl.grid(row=0, column=1, sticky="w")

        # Description
        ctk.CTkLabel(
            parent, text=t("tpl_description_label"),
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=24, pady=(14, 2))

        self._desc_entry = ctk.CTkEntry(
            parent, placeholder_text=t("tpl_description_ph"),
            font=FONT_NORMAL, height=36,
        )
        self._desc_entry.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 12))

        # Upload button
        self._upload_btn = ctk.CTkButton(
            parent, text=t("tpl_upload_btn"), font=(*FONT_NORMAL[:2], "bold"),
            fg_color=GREEN if "GREEN" in dir() else BLUE_MID,
            hover_color=NAVY_DARK, height=42,
            command=self._upload_template,
        )
        self._upload_btn.grid(row=5, column=0, sticky="ew", padx=24, pady=(4, 8))

        # Status message
        self._upload_status = ctk.CTkLabel(
            parent, text="", font=FONT_NORMAL,
            text_color=TEXT_PRIMARY, anchor="w", wraplength=380,
        )
        self._upload_status.grid(row=6, column=0, sticky="w", padx=24, pady=(0, 20))

    # ── Logic: info loading ───────────────────────────────────────────────────

    def _load_info(self):
        self._source_lbl.configure(text=t("tpl_loading"))
        for lbl in self._info_labels.values():
            lbl.configure(text="")
        self._dl_btn.configure(state="disabled")

        def _fetch():
            try:
                info = self.api.get_excel_template_info()
                self.after(0, lambda: self._show_info(info))
            except Exception as e:
                self.after(0, lambda: self._source_lbl.configure(
                    text=f"❌ {e}", text_color=COLOR_ERROR if "COLOR_ERROR" in dir() else "#C0392B"
                ))

        threading.Thread(target=_fetch, daemon=True).start()

    def _show_info(self, info: dict):
        source = info.get("source", "filesystem")

        if source == "database":
            self._source_lbl.configure(text=t("tpl_source_db"), text_color=NAVY_LIGHT)

            version  = info.get("version", "?")
            filename = info.get("filename", "")
            size_b   = info.get("file_size", 0)
            uploader = info.get("uploaded_by") or "—"
            uploaded = info.get("uploaded_at", "")
            desc     = info.get("description") or ""

            # Show version badge in header
            self._version_badge.configure(text=f"v{version}")

            self._info_labels["tpl_version"].configure(
                text=t("tpl_version", version=version))
            self._info_labels["tpl_filename"].configure(
                text=t("tpl_filename", filename=filename))
            self._info_labels["tpl_size"].configure(
                text=t("tpl_size", size=_fmt_size(size_b)))
            self._info_labels["tpl_uploaded_by"].configure(
                text=t("tpl_uploaded_by", name=uploader))
            self._info_labels["tpl_uploaded_at"].configure(
                text=t("tpl_uploaded_at", date=_fmt_date(uploaded) if uploaded else "—"))
            self._info_labels["tpl_description"].configure(
                text=t("tpl_description", desc=desc) if desc else "")

            self._dl_btn.configure(state="normal")

        else:
            self._source_lbl.configure(text=t("tpl_source_fs"), text_color=TEXT_SECONDARY)
            self._version_badge.configure(text="")
            for lbl in self._info_labels.values():
                lbl.configure(text="")
            self._dl_btn.configure(state="disabled")

    # ── Logic: download ───────────────────────────────────────────────────────

    def _download_template(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsm",
            filetypes=[("Excel Macro", "*.xlsm"), ("All", "*.*")],
            initialfile="WV_template.xlsm",
        )
        if not path:
            return

        def _do():
            try:
                ok = self.api.download_excel_template(path)
                if ok:
                    self.after(0, lambda: messagebox.showinfo(
                        "OK", f"Шаблон сохранён:\n{path}"))
                else:
                    self.after(0, lambda: messagebox.showwarning(
                        "Нет шаблона", "В БД нет активного шаблона"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Ошибка", str(e)))

        threading.Thread(target=_do, daemon=True).start()

    # ── Logic: upload ─────────────────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Excel Macro", "*.xlsm"), ("All", "*.*")]
        )
        if path:
            if not path.lower().endswith(".xlsm"):
                self._upload_status.configure(
                    text=t("tpl_wrong_type"), text_color="#E67E22")
                return
            self._selected_file = path
            fname = path.replace("\\", "/").split("/")[-1]
            self._file_lbl.configure(
                text=fname, text_color=TEXT_PRIMARY)
            self._upload_status.configure(text="")

    def _upload_template(self):
        if not self._selected_file:
            self._upload_status.configure(
                text=t("tpl_wrong_type"), text_color="#E67E22")
            return
        if not self._selected_file.lower().endswith(".xlsm"):
            self._upload_status.configure(
                text=t("tpl_wrong_type"), text_color="#E67E22")
            return

        desc = self._desc_entry.get().strip()
        self._upload_btn.configure(state="disabled")
        self._upload_status.configure(
            text=t("tpl_uploading"), text_color=TEXT_SECONDARY)

        def _do():
            try:
                result = self.api.upload_excel_template(self._selected_file, desc)
                version = result.get("version", "?")
                self.after(0, lambda: self._on_upload_ok(version))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_upload_err(err))

        threading.Thread(target=_do, daemon=True).start()

    def _on_upload_ok(self, version):
        self._upload_btn.configure(state="normal")
        self._upload_status.configure(
            text=t("tpl_upload_ok", version=version), text_color="#1E8449")
        self._selected_file = ""
        self._file_lbl.configure(text=t("tpl_no_file"), text_color=TEXT_SECONDARY)
        self._desc_entry.delete(0, "end")
        self._load_info()   # refresh info panel

    def _on_upload_err(self, error: str):
        self._upload_btn.configure(state="normal")
        self._upload_status.configure(
            text=t("tpl_upload_error", error=error), text_color="#C0392B")

    # ── Public: called on tab switch ──────────────────────────────────────────

    def load(self):
        """Called when page becomes visible."""
        self._load_info()

    def refresh_lang(self):
        self._title_lbl.configure(text=t("tpl_title"))
        self._subtitle_lbl.configure(text=t("tpl_subtitle"))
        self._load_info()
