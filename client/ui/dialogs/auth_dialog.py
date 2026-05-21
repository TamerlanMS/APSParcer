import customtkinter as ctk
from assets.theme import *
from locales.strings import Lang, t
from services.config import AppConfig
from services.api_service import ApiService
import threading
from typing import Callable, Optional


class AuthDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: AppConfig, api: ApiService,
                 on_success: Callable, on_cancel: Optional[Callable] = None):
        super().__init__(parent)
        self.config     = config
        self.api        = api
        self.on_success = on_success
        self.on_cancel  = on_cancel

        self.title(t("auth_title"))
        self.configure(fg_color=BG_MAIN)
        self.resizable(True, True)

        W, H = 520, 580
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        self.minsize(460, 520)

        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._drag_x = 0
        self._drag_y = 0
        self._build()

    # ── Drag ─────────────────────────────────────────────────────────────────
    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", lambda e: self._drag_start(e))
        widget.bind("<B1-Motion>",     lambda e: self._drag_move(e))

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build(self):
        pad = PAD_XL

        # Заголовок — за него тащим окно
        header = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(header, text="🔐  APS Parser",
                                  font=FONT_LOGO, text_color="white")
        title_lbl.pack(side="left", padx=20, pady=12)

        hint = ctk.CTkLabel(header, text="⠿  перетащите",
                             font=FONT_SMALL, text_color=TEXT_NAV_LIGHT)
        hint.pack(side="right", padx=16)

        for w in [header, title_lbl, hint]:
            self._bind_drag(w)

        self.sub_lbl = ctk.CTkLabel(self, text=t("auth_subtitle"),
                                     font=FONT_NORMAL, text_color=TEXT_SECONDARY)
        self.sub_lbl.pack(pady=(18, 0))

        ctk.CTkFrame(self, height=1, fg_color="#D5D8DC").pack(
            fill="x", padx=pad, pady=(14, 0))

        # Язык
        lang_row = ctk.CTkFrame(self, fg_color="transparent")
        lang_row.pack(pady=(12, 0), padx=pad, fill="x")
        ctk.CTkLabel(lang_row, text="Язык / Тіл:", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.lang_var = ctk.StringVar(value=Lang.get())
        ctk.CTkRadioButton(lang_row, text="Русский", variable=self.lang_var,
                           value="ru", command=self._on_lang_change,
                           font=FONT_NORMAL).pack(side="left", padx=12)
        ctk.CTkRadioButton(lang_row, text="Қазақша", variable=self.lang_var,
                           value="kz", command=self._on_lang_change,
                           font=FONT_NORMAL).pack(side="left")

        # Форма
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(pady=16, padx=pad, fill="x")

        self.server_lbl = ctk.CTkLabel(form, text=t("auth_server"),
                                        font=FONT_NORMAL, text_color=NAVY, anchor="w")
        self.server_lbl.pack(fill="x")
        self.server_entry = ctk.CTkEntry(form, placeholder_text=t("auth_server_ph"),
                                          height=40, font=FONT_NORMAL,
                                          border_color=NAVY_LIGHT)
        self.server_entry.pack(fill="x", pady=(4, 14))
        if self.config.server_url:
            self.server_entry.insert(0, self.config.server_url)

        self.key_lbl = ctk.CTkLabel(form, text=t("auth_key"),
                                     font=FONT_NORMAL, text_color=NAVY, anchor="w")
        self.key_lbl.pack(fill="x")

        key_row = ctk.CTkFrame(form, fg_color="transparent")
        key_row.pack(fill="x", pady=(4, 0))

        self.key_entry = ctk.CTkEntry(key_row, placeholder_text=t("auth_key_ph"),
                                       height=40, font=FONT_NORMAL,
                                       show="•", border_color=NAVY_LIGHT)
        self.key_entry.pack(side="left", fill="x", expand=True)
        # Подставляем сохранённый ключ
        if self.config.api_key:
            self.key_entry.insert(0, self.config.api_key)

        self._show_key = False
        self.eye_btn = ctk.CTkButton(
            key_row, text="👁", width=44, height=40,
            fg_color=NAVY_LIGHT, hover_color=BLUE_MID,
            command=self._toggle_eye, corner_radius=RADIUS_SM
        )
        self.eye_btn.pack(side="left", padx=(8, 0))

        self.status_lbl = ctk.CTkLabel(self, text="", font=FONT_NORMAL,
                                        text_color=NAVY_LIGHT, wraplength=420)
        self.status_lbl.pack(pady=(12, 0), padx=pad)

        self.connect_btn = ctk.CTkButton(
            self, text=t("auth_connect"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=48, corner_radius=RADIUS_MD,
            command=self._try_connect
        )
        self.connect_btn.pack(pady=16, padx=pad, fill="x")

        self.server_entry.bind("<Return>", lambda e: self.key_entry.focus())
        self.key_entry.bind("<Return>",   lambda e: self._try_connect())

    # ── Логика ───────────────────────────────────────────────────────────────
    def _on_lang_change(self):
        Lang.set(self.lang_var.get())
        self.sub_lbl.configure(text=t("auth_subtitle"))
        self.server_lbl.configure(text=t("auth_server"))
        self.server_entry.configure(placeholder_text=t("auth_server_ph"))
        self.key_lbl.configure(text=t("auth_key"))
        self.key_entry.configure(placeholder_text=t("auth_key_ph"))
        self.connect_btn.configure(text=t("auth_connect"))

    def _toggle_eye(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "•")
        self.eye_btn.configure(text="🙈" if self._show_key else "👁")

    def _try_connect(self):
        server = self.server_entry.get().strip().rstrip("/")
        key    = self.key_entry.get().strip()

        if not server:
            self.status_lbl.configure(text=t("auth_no_server"), text_color="#E74C3C")
            return
        if not key:
            self.status_lbl.configure(text=t("auth_no_key"), text_color="#E74C3C")
            return

        self.connect_btn.configure(state="disabled",
                                   text="⏳  " + t("auth_checking"))
        self.status_lbl.configure(text=t("auth_checking"), text_color=NAVY_LIGHT)

        self.config.server_url = server
        self.config.api_key    = key
        self.config.language   = self.lang_var.get()

        threading.Thread(target=self._check_thread, daemon=True).start()

    def _check_thread(self):
        ok, msg = self.api.validate_key()
        self.after(0, lambda: self._on_result(ok, msg))

    def _on_result(self, ok: bool, msg: str):
        if ok:
            self.config.save()
            self.status_lbl.configure(text=t("auth_success"), text_color="#27AE60")
            self.connect_btn.configure(text=t("auth_connect"))
            self.after(500, self._finish_ok)
        else:
            err_key = "auth_invalid" if "invalid" in msg or "403" in msg else "auth_no_conn"
            self.status_lbl.configure(text=t(err_key), text_color="#E74C3C")
            self.connect_btn.configure(state="normal", text=t("auth_connect"))

    def _finish_ok(self):
        self.destroy()
        self.on_success()

    def _on_close(self):
        self.destroy()
        if self.on_cancel:
            self.on_cancel()
