"""Upload page -- multi-PDF upload with per-file progress."""
import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import threading
import os
import re as _re

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService

try:
    from tkinterdnd2 import DND_FILES
except Exception:
    DND_FILES = "DND_Files"

_STAGE_LABELS = {
    "upload":      "Отправка...",
    "detect":      "Анализ структуры...",
    "extract":     "Извлечение таблиц...",
    "ocr_check":   "Проверка OCR...",
    "ocr_start":   "Запуск OCR...",
    "ocr_page":    "OCR страниц...",
    "parse":       "Разбор позиций...",
    "tech_params": "Параметры (ИИ)...",
    "match":       "Подбор в БД...",
    "save":        "Сохранение...",
    "done":        "Готово!",
    "error":       "Ошибка",
}


def _fmt_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} МБ"
    if n >= 1024:
        return f"{n / 1024:.0f} КБ"
    return f"{n} Б"


class _FileRow(ctk.CTkFrame):
    """One row in the file list (before processing starts)."""

    def __init__(self, parent, name: str, size: int, on_remove):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_SM,
                         border_width=1, border_color="#D5D8DC")
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="PDF", font=("Calibri", 9, "bold"),
                     text_color="#E74C3C", width=28).grid(row=0, column=0,
                     padx=(10, 4), pady=6)
        ctk.CTkLabel(self, text=name, font=FONT_NORMAL, text_color=NAVY,
                     anchor="w").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(self, text=_fmt_size(size), font=FONT_SMALL,
                     text_color=TEXT_SECONDARY, width=72,
                     anchor="e").grid(row=0, column=2, padx=(4, 6))
        ctk.CTkButton(
            self, text="x", width=28, height=28, corner_radius=6,
            fg_color="#E74C3C", hover_color="#C0392B",
            font=("Calibri", 12, "bold"), text_color="white",
            command=on_remove,
        ).grid(row=0, column=3, padx=(0, 8), pady=6)


class _ProgressRow(ctk.CTkFrame):
    """One row in the progress list (during/after processing)."""

    def __init__(self, parent, name: str):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_SM,
                         border_width=1, border_color="#D5D8DC")
        self.grid_columnconfigure(2, weight=1)

        self._icon = ctk.CTkLabel(self, text="...", font=FONT_SMALL,
                                   text_color=TEXT_SECONDARY, width=22)
        self._icon.grid(row=0, column=0, padx=(10, 6), pady=(8, 2))

        ctk.CTkLabel(self, text=name, font=("Calibri", 12, "bold"),
                     text_color=NAVY, anchor="w",
                     width=260).grid(row=0, column=1, sticky="w", padx=(0, 12))

        self._stage = ctk.CTkLabel(self, text="Ожидание...", font=FONT_SMALL,
                                    text_color=TEXT_SECONDARY, anchor="w")
        self._stage.grid(row=0, column=2, sticky="w")

        self._pct_lbl = ctk.CTkLabel(self, text="0%", font=FONT_SMALL,
                                      text_color=TEXT_SECONDARY, width=36, anchor="e")
        self._pct_lbl.grid(row=0, column=3, padx=(4, 10))

        self._bar = ctk.CTkProgressBar(self, height=8, corner_radius=4,
                                        progress_color=NAVY_LIGHT, fg_color="#D5D8DC")
        self._bar.set(0)
        self._bar.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=(2, 8))

    def update_progress(self, pct: int, stage: str, msg: str):
        self._bar.set(pct / 100)
        self._pct_lbl.configure(text=f"{pct}%")
        label = _STAGE_LABELS.get(stage, stage)
        short = msg[:60] if msg else label
        self._stage.configure(text=short)

    def mark_done(self, n_items: int):
        self._icon.configure(text="OK", text_color="#27AE60")
        self._bar.set(1.0)
        self._pct_lbl.configure(text="100%")
        self._stage.configure(text=f"Готово! {n_items} позиций", text_color="#27AE60")
        self._bar.configure(progress_color="#27AE60")

    def mark_error(self, msg: str):
        self._icon.configure(text="!!", text_color="#E74C3C")
        self._bar.configure(progress_color="#E74C3C")
        self._stage.configure(text=msg[:70], text_color="#E74C3C")


class UploadPage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api = api
        self.app = app

        self._files: list = []      # [{"path": str, "name": str, "size": int}]
        self._processing = False
        self._ai_mode = ctk.BooleanVar(value=True)
        self._seg_ss  = ctk.BooleanVar(value=False)
        self._seg_os  = ctk.BooleanVar(value=False)
        self._seg_sil = ctk.BooleanVar(value=False)
        self._prog_rows: dict = {}  # {file_idx: _ProgressRow}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build()

    # ------------------------------------------------------------------ layout

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

    def _build_upload_tab(self):
        tab = self.tabview.tab(t("upload_tab_upload"))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)
        pad = PAD_LG

        # Title
        ctk.CTkLabel(tab, text="Мультизагрузка PDF",
                     font=FONT_TITLE, text_color=NAVY, anchor="w",
                     ).grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 2))
        ctk.CTkLabel(
            tab,
            text=("Добавьте один или несколько PDF-файлов со спецификацией. "
                  "Файлы обрабатываются параллельно."),
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, anchor="w", wraplength=700,
        ).grid(row=1, column=0, sticky="w", padx=pad, pady=(0, PAD_MD))

        # Drop zone
        self.drop_zone = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=RADIUS_LG,
            border_width=2, border_color="#AEB6BF",
        )
        self.drop_zone.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, 6))
        self.drop_zone.grid_columnconfigure(0, weight=1)

        self._drop_icon  = ctk.CTkLabel(self.drop_zone, text="[PDF]",
                                         font=("Calibri", 28, "bold"), text_color="#AEB6BF")
        self._drop_icon.grid(row=0, pady=(20, 4))
        self._drop_title = ctk.CTkLabel(self.drop_zone,
                                         text="Перетащите PDF-файлы сюда",
                                         font=FONT_HEADING, text_color=NAVY)
        self._drop_title.grid(row=1)
        self._drop_sub   = ctk.CTkLabel(self.drop_zone,
                                         text="Можно выбрать несколько файлов одновременно",
                                         font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self._drop_sub.grid(row=2, pady=(2, 20))
        self._bind_dnd()

        # Browse button
        self.browse_btn = ctk.CTkButton(
            tab, text="Добавить файлы",
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=40, corner_radius=RADIUS_MD, width=200,
            command=self._browse,
        )
        self.browse_btn.grid(row=3, pady=(0, PAD_SM))

        # File list section
        list_outer = ctk.CTkFrame(tab, fg_color="transparent")
        list_outer.grid(row=4, column=0, sticky="nsew", padx=pad, pady=(0, 4))
        list_outer.grid_columnconfigure(0, weight=1)
        list_outer.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(list_outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        self._files_count_lbl = ctk.CTkLabel(
            hdr, text="Файлы не выбраны",
            font=(*FONT_SMALL[:2], "bold"), text_color=TEXT_SECONDARY, anchor="w",
        )
        self._files_count_lbl.grid(row=0, column=0, sticky="w")

        self._clear_btn = ctk.CTkButton(
            hdr, text="Очистить всё",
            font=FONT_SMALL, fg_color="transparent", hover_color="#FDECEA",
            text_color="#E74C3C", height=24, width=90, corner_radius=RADIUS_SM,
            command=self._clear_all,
        )
        self._clear_btn.grid(row=0, column=1)
        self._clear_btn.grid_remove()

        self._file_list_frame = ctk.CTkScrollableFrame(
            list_outer, fg_color="transparent", height=130,
        )
        self._file_list_frame.grid(row=1, column=0, sticky="ew")
        self._file_list_frame.grid_columnconfigure(0, weight=1)

        # Options row
        opts = ctk.CTkFrame(tab, fg_color=BG_CARD, corner_radius=RADIUS_MD,
                             border_width=1, border_color="#D0D3D4")
        opts.grid(row=5, column=0, sticky="ew", padx=pad, pady=(PAD_SM, 4))
        opts.grid_columnconfigure(2, weight=1)

        self.ai_switch = ctk.CTkSwitch(
            opts, text="", variable=self._ai_mode,
            progress_color=NAVY_LIGHT, button_color=NAVY,
            button_hover_color=NAVY_DARK, width=46, height=24,
        )
        self.ai_switch.grid(row=0, column=0, padx=(14, 4), pady=8)
        ctk.CTkLabel(opts, text="ИИ-режим подбора",
                     font=(*FONT_SMALL[:2], "bold"), text_color=NAVY,
                     ).grid(row=0, column=1, padx=(0, 16), pady=8)

        self.seg_lbl = ctk.CTkLabel(opts, text=t("upload_seg_label") + ":",
                                     font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.seg_lbl.grid(row=0, column=2, sticky="e", padx=(0, 8))

        for attr, var, key, col in [
            ("_seg_ss_sw",  self._seg_ss,  "seg_ss",  3),
            ("_seg_os_sw",  self._seg_os,  "seg_os",  4),
            ("_seg_sil_sw", self._seg_sil, "seg_sil", 5),
        ]:
            sw = ctk.CTkSwitch(
                opts, text=t(key), variable=var,
                progress_color=NAVY_LIGHT, button_color=NAVY,
                button_hover_color=NAVY_DARK, font=FONT_SMALL,
            )
            sw.grid(row=0, column=col, padx=6, pady=8)
            setattr(self, attr, sw)

        # Progress section (hidden until processing)
        self._prog_section = ctk.CTkFrame(tab, fg_color="transparent")
        self._prog_section.grid(row=6, column=0, sticky="ew", padx=pad, pady=(4, 0))
        self._prog_section.grid_columnconfigure(0, weight=1)
        self._prog_section.grid_remove()

        ctk.CTkLabel(
            self._prog_section, text="Ход обработки",
            font=(*FONT_SMALL[:2], "bold"), text_color=NAVY, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._prog_list = ctk.CTkScrollableFrame(
            self._prog_section, fg_color="transparent", height=160,
        )
        self._prog_list.grid(row=1, column=0, sticky="ew")
        self._prog_list.grid_columnconfigure(0, weight=1)

        self._summary_lbl = ctk.CTkLabel(
            self._prog_section, text="",
            font=(*FONT_NORMAL[:2], "bold"), text_color=NAVY_LIGHT, anchor="w",
        )
        self._summary_lbl.grid(row=2, column=0, sticky="w", pady=(6, 0))

        # Submit button
        self.send_btn = ctk.CTkButton(
            tab, text="Обработать",
            font=(*FONT_HEADING[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=50, corner_radius=RADIUS_MD, width=320,
            state="disabled",
            command=self._send,
        )
        self.send_btn.grid(row=7, pady=(PAD_SM, pad))

    # ---------------------------------------------------------- history tab

    def _build_history_tab(self):
        tab = self.tabview.tab(t("upload_tab_history"))
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=PAD_MD, pady=(PAD_MD, 6))
        top.grid_columnconfigure(0, weight=1)

        self.hist_title_lbl = ctk.CTkLabel(
            top, text=t("upload_tab_history"),
            font=FONT_TITLE, text_color=NAVY, anchor="w",
        )
        self.hist_title_lbl.grid(row=0, column=0, sticky="w")

        self.hist_refresh_btn = ctk.CTkButton(
            top, text=t("upload_hist_refresh"),
            font=FONT_SMALL, fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=32, width=140, corner_radius=RADIUS_SM,
            command=self._load_history,
        )
        self.hist_refresh_btn.grid(row=0, column=1)

        style = ttk.Style()
        style.configure("Hist.Treeview", rowheight=30, font=("Calibri", 12),
                        background=BG_CARD, fieldbackground=BG_CARD)
        style.configure("Hist.Treeview.Heading", background=NAVY, foreground="white",
                        font=("Calibri", 12, "bold"))
        style.map("Hist.Treeview", background=[("selected", BLUE_MID)])

        cols = ["who", "file", "project", "date"]
        self.hist_tree = ttk.Treeview(tab, columns=cols, show="headings",
                                       style="Hist.Treeview")
        for col, key, w in [
            ("who",     "upload_hist_who",     180),
            ("file",    "upload_hist_file",    220),
            ("project", "upload_hist_project", 420),
            ("date",    "upload_hist_date",    150),
        ]:
            self.hist_tree.heading(col, text=t(key))
            self.hist_tree.column(col, width=w, minwidth=80)

        vsb = ttk.Scrollbar(tab, orient="vertical",   command=self.hist_tree.yview)
        hsb = ttk.Scrollbar(tab, orient="horizontal", command=self.hist_tree.xview)
        self.hist_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.hist_tree.grid(row=1, column=0, sticky="nsew", padx=(PAD_MD, 0))
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="ew", padx=(PAD_MD, 0))

        self.hist_status_lbl = ctk.CTkLabel(
            tab, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY,
        )
        self.hist_status_lbl.grid(row=3, column=0, pady=(4, PAD_SM))
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
                r.get("full_name", "---"),
                r.get("filename",  "---"),
                r.get("project_name", "---"),
                r.get("uploaded_at", "---"),
            ))
        count = len(rows)
        key = "upload_hist_count_1" if count == 1 else "upload_hist_count"
        self.hist_status_lbl.configure(text=t(key, count=count),
                                        text_color=TEXT_SECONDARY)
        self.hist_refresh_btn.configure(state="normal")

    def _history_error(self, error: str):
        self.hist_status_lbl.configure(
            text=t("upload_hist_error") + f": {error}", text_color="#E74C3C",
        )
        self.hist_refresh_btn.configure(state="normal")

    # ---------------------------------------------------------- file management

    def _bind_dnd(self):
        for w in [self.drop_zone, self._drop_icon, self._drop_title, self._drop_sub]:
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _on_drop(self, event):
        raw = (event.data or "").strip()
        paths = _re.findall(r'\{([^}]+)\}|(\S+)', raw)
        paths = [a or b for a, b in paths]
        pdf_paths = [p for p in paths if p.lower().endswith(".pdf")]
        non_pdf   = [p for p in paths if not p.lower().endswith(".pdf")]
        if non_pdf:
            messagebox.showwarning("", t("upload_wrong_type"))
        if pdf_paths:
            self._add_files(pdf_paths)

    def _browse(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("PDF", "*.pdf"), ("All", "*.*")],
        )
        if paths:
            self._add_files(list(paths))

    def _add_files(self, paths: list):
        existing = {f["path"] for f in self._files}
        for p in paths:
            if p not in existing:
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                self._files.append({"path": p, "name": os.path.basename(p), "size": size})
                existing.add(p)
        self._rebuild_file_list()

    def _remove_file(self, path: str):
        self._files = [f for f in self._files if f["path"] != path]
        self._rebuild_file_list()

    def _clear_all(self):
        self._files.clear()
        self._rebuild_file_list()

    def _rebuild_file_list(self):
        for w in self._file_list_frame.winfo_children():
            w.destroy()

        n = len(self._files)
        if n == 0:
            self._files_count_lbl.configure(text="Файлы не выбраны",
                                             text_color=TEXT_SECONDARY)
            self._clear_btn.grid_remove()
            self.send_btn.configure(state="disabled", text="Обработать")
            self.drop_zone.configure(border_color="#AEB6BF", fg_color=BG_CARD)
            self._drop_icon.configure(text="[PDF]", text_color="#AEB6BF")
            self._drop_title.configure(text="Перетащите PDF-файлы сюда",
                                        text_color=NAVY)
            self._drop_sub.configure(
                text="Можно выбрать несколько файлов одновременно",
                text_color=TEXT_SECONDARY,
            )
        else:
            word = "файл" if n == 1 else ("файла" if n < 5 else "файлов")
            self._files_count_lbl.configure(
                text=f"Выбрано: {n} {word}", text_color=NAVY,
            )
            self._clear_btn.grid()
            self.send_btn.configure(
                state="normal",
                text=f"Обработать  ({n} {word})",
            )
            self.drop_zone.configure(border_color="#27AE60", fg_color="#EAFAF1")
            self._drop_icon.configure(text=f"{n} PDF", text_color="#27AE60")
            word2 = "выбран" if n == 1 else ("выбрано" if n < 5 else "выбрано")
            self._drop_title.configure(
                text=f"{n} {word} {word2}", text_color="#27AE60",
            )
            self._drop_sub.configure(
                text="Перетащите ещё файлы или нажмите «Добавить файлы»",
                text_color=TEXT_SECONDARY,
            )

        for i, f in enumerate(self._files):
            path = f["path"]
            row = _FileRow(
                self._file_list_frame,
                name=f["name"], size=f["size"],
                on_remove=lambda p=path: self._remove_file(p),
            )
            row.grid(row=i, column=0, sticky="ew", pady=(0, 4))

    # ---------------------------------------------------------- processing

    def _get_segments(self) -> list:
        segs = []
        if self._seg_ss.get():  segs.append("ss")
        if self._seg_os.get():  segs.append("os")
        if self._seg_sil.get(): segs.append("sil")
        return segs

    def on_login(self):
        role = getattr(self.app.config, "user_role", "manager")
        seg  = getattr(self.app.config, "user_segment", "ss")
        if role in ("superadmin", "administrator"):
            # Admins have access to all segments — enable all by default
            self._seg_ss.set(True)
            self._seg_os.set(True)
            self._seg_sil.set(True)
        else:
            self._seg_ss.set(seg == "ss")
            self._seg_os.set(seg == "os")
            self._seg_sil.set(seg == "sil")

    def _send(self):
        if self._processing or not self._files:
            return
        segments = self._get_segments()
        if not segments:
            messagebox.showwarning(
                "Сегмент не выбран",
                "Выберите хотя бы один сегмент базы\n"
                "(Слаботочные / Освещение / Силовые)\nперед отправкой.",
            )
            return

        self._processing = True
        self.send_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")

        # Build progress UI
        for w in self._prog_list.winfo_children():
            w.destroy()
        self._prog_rows.clear()
        self._summary_lbl.configure(text="")
        self._prog_section.grid()

        paths = [f["path"] for f in self._files]
        for idx, f in enumerate(self._files):
            row = _ProgressRow(self._prog_list, f["name"])
            row.grid(row=idx, column=0, sticky="ew", pady=(0, 4))
            self._prog_rows[idx] = row

        ai = self._ai_mode.get()

        def _progress_cb(file_idx, filename, pct, stage, msg):
            self.after(0, lambda: self._on_progress(file_idx, pct, stage, msg))

        def _file_done_cb(file_idx, filename, result):
            n = result.get("total", 0) if result else 0
            self.after(0, lambda: self._on_file_done(file_idx, n))

        def _worker():
            try:
                results = self.api.parse_pdf_multi_stream(
                    paths,
                    progress_cb=_progress_cb,
                    file_done_cb=_file_done_cb,
                    ai_mode=ai,
                    segments=segments,
                )
                self.after(0, lambda: self._on_all_done(results))
            except Exception as e:
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, file_idx: int, pct: int, stage: str, msg: str):
        row = self._prog_rows.get(file_idx)
        if row:
            if stage == "error":
                row.mark_error(msg)
            else:
                row.update_progress(pct, stage, msg)

    def _on_file_done(self, file_idx: int, n_items: int):
        row = self._prog_rows.get(file_idx)
        if row:
            row.mark_done(n_items)

    def _on_all_done(self, results: list):
        self._processing = False
        self.send_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")

        ok_results = [r for r in results if r]
        total_items = sum(r.get("total", 0) for r in ok_results)
        n_ok  = len(ok_results)
        n_all = len(self._files)

        self._summary_lbl.configure(
            text=f"Обработано: {n_ok}/{n_all} файлов  |  Всего позиций: {total_items}",
            text_color=NAVY_LIGHT if n_ok == n_all else "#E67E22",
        )

        if not ok_results:
            messagebox.showerror("Ошибка", "Ни один файл не был успешно обработан.")
            return

        self.app.on_multi_result_ready(ok_results)
        self.after(1500, self._load_history)

    def _on_error(self, error: str):
        self._processing = False
        self.send_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        messagebox.showerror(t("upload_error_title"), t("upload_error_msg") + error)

    # ---------------------------------------------------------- reset / lang

    def reset(self):
        self._files.clear()
        self._processing = False
        self._rebuild_file_list()
        self._prog_section.grid_remove()
        self._summary_lbl.configure(text="")

    def refresh_lang(self):
        self.hist_title_lbl.configure(text=t("upload_tab_history"))
        self.hist_refresh_btn.configure(text=t("upload_hist_refresh"))
        for col, key in [("who",     "upload_hist_who"),
                         ("file",    "upload_hist_file"),
                         ("project", "upload_hist_project"),
                         ("date",    "upload_hist_date")]:
            self.hist_tree.heading(col, text=t(key))
        self.seg_lbl.configure(text=t("upload_seg_label") + ":")
        self._seg_ss_sw.configure(text=t("seg_ss"))
        self._seg_os_sw.configure(text=t("seg_os"))
        self._seg_sil_sw.configure(text=t("seg_sil"))
