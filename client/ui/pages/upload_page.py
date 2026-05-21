import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading, os

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService

# Опциональный DnD — на корневом окне MainApp вызывается TkinterDnD._require()
try:
    from tkinterdnd2 import DND_FILES
except Exception:
    DND_FILES = "DND_Files"


class UploadPage(ctk.CTkFrame):
    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api  = api
        self.app  = app
        self._path = None
        self._worker = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build()

    def _build(self):
        pad = PAD_XL

        # Заголовок
        self.title_lbl = ctk.CTkLabel(self, text=t("upload_title"),
                                       font=FONT_TITLE, text_color=NAVY, anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 4))

        self.desc_lbl = ctk.CTkLabel(self, text=t("upload_desc"),
                                      font=FONT_NORMAL, text_color=TEXT_SECONDARY,
                                      anchor="w", wraplength=700)
        self.desc_lbl.grid(row=1, column=0, sticky="w", padx=pad, pady=(0, PAD_MD))

        # Drop zone
        self.drop_zone = ctk.CTkFrame(
            self, fg_color=BG_CARD,
            corner_radius=RADIUS_LG,
            border_width=2, border_color="#AEB6BF"
        )
        self.drop_zone.grid(row=2, column=0, sticky="ew",
                            padx=pad, pady=(0, PAD_MD))
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

        # Включаем drag-and-drop через tkinterdnd2 (если доступен)
        self._bind_dnd()

        # Кнопка выбора файла
        self.browse_btn = ctk.CTkButton(
            self, text=t("upload_browse"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=44, corner_radius=RADIUS_MD, width=220,
            command=self._browse
        )
        self.browse_btn.grid(row=3, pady=4)

        # Имя файла
        self.file_lbl = ctk.CTkLabel(self, text=t("upload_no_file"),
                                      font=FONT_NORMAL, text_color=TEXT_SECONDARY)
        self.file_lbl.grid(row=4, pady=(0, 8))

        # Прогресс-бар
        self.progress = ctk.CTkProgressBar(self, width=500,
                                            progress_color=NAVY_LIGHT,
                                            fg_color="#D5D8DC")
        self.progress.set(0)
        self.progress.grid(row=5, pady=(0, 4))
        self.progress.grid_remove()

        self.progress_lbl = ctk.CTkLabel(self, text="", font=FONT_SMALL,
                                          text_color=TEXT_SECONDARY)
        self.progress_lbl.grid(row=6)
        self.progress_lbl.grid_remove()

        # Кнопка отправки
        self.send_btn = ctk.CTkButton(
            self, text=t("upload_send"),
            font=(*FONT_HEADING[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=52, corner_radius=RADIUS_MD, width=320,
            state="disabled",
            command=self._send
        )
        self.send_btn.grid(row=7, pady=(12, pad))

    def _bind_dnd(self):
        """Включаем drag-and-drop на drop_zone и всех её детях.
        Корневое окно MainApp уже инициализировало TkinterDnD._require()."""
        targets = [self.drop_zone, self.drop_icon, self.drop_title, self.drop_sub]
        for w in targets:
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
                w.configure(cursor="hand2")
            except Exception as e:
                # Логируем в консоль (видно если запускать .exe с console=True)
                print(f"[DnD] не удалось зарегистрировать {w}: {e}")

    def _on_drop(self, event):
        # event.data: список путей в фигурных скобках, например "{C:/path/file.pdf}"
        raw = (event.data or "").strip()
        # Берём только первый файл если кинули несколько
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
            title=t("upload_browse"),
            filetypes=[("PDF", "*.pdf"), ("All", "*.*")]
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._path = path
        name  = os.path.basename(path)
        size  = os.path.getsize(path) / 1024
        self.file_lbl.configure(
            text=f"✅  {name}  ({size:.0f} КБ)", text_color=NAVY_LIGHT
        )
        self.send_btn.configure(state="normal")
        self.drop_zone.configure(border_color=NAVY_LIGHT, fg_color=BLUE_PALE)

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

    def _on_error(self, error: str):
        self.progress.grid_remove()
        self.progress_lbl.grid_remove()
        self.send_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        messagebox.showerror(t("upload_error_title"), t("upload_error_msg") + error)

    def reset(self):
        """Сброс состояния страницы — вызывается из preview._reset()."""
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
        if not self._path:
            self.file_lbl.configure(text=t("upload_no_file"))
