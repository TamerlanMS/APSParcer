"""
Two-step authorisation dialog.
  Step 1: server URL + API key (connection check)
  Step 2: user dropdown + password (JWT login)
"""
import os
import customtkinter as ctk
from PIL import Image
from assets.theme import *
from locales.strings import Lang, t
from services.config import AppConfig
from services.api_service import ApiService
import threading
from typing import Callable, Optional

# ── Logo image (loaded once) ─────────────────────────────────────────────────
_LOGO_IMG = None

def _get_logo() -> Optional[ctk.CTkImage]:
    global _LOGO_IMG
    if _LOGO_IMG is not None:
        return _LOGO_IMG
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "..", "assets", "logo.png")
        pil  = Image.open(os.path.normpath(path))
        # Scale to fit header (target height 50 px, keep aspect ratio)
        target_h = 50
        scale    = target_h / pil.height
        target_w = int(pil.width * scale)
        _LOGO_IMG = ctk.CTkImage(light_image=pil, dark_image=pil,
                                  size=(target_w, target_h))
    except Exception:
        _LOGO_IMG = None
    return _LOGO_IMG


class AuthDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: AppConfig, api: ApiService,
                 on_success: Callable, on_cancel: Optional[Callable] = None):
        super().__init__(parent)
        self.config     = config
        self.api        = api
        self.on_success = on_success
        self.on_cancel  = on_cancel

        self._users: list = []
        self._users_loaded = False
        self._step = 1

        self.title(t("auth_title"))
        self.configure(fg_color=BG_MAIN)
        self.resizable(True, True)

        W, H = 520, 640
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        self.minsize(460, 580)

        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._drag_x = 0
        self._drag_y = 0

        self._build_header()
        self._build_step1()
        self._build_step2()
        self._show_step(1)

    # ── Drag ─────────────────────────────────────────────────────────────────
    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", lambda e: (
            setattr(self, "_drag_x", e.x_root - self.winfo_x()),
            setattr(self, "_drag_y", e.y_root - self.winfo_y()),
        ))
        widget.bind("<B1-Motion>", lambda e: self.geometry(
            f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}"
        ))

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        self._header = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, height=70)
        self._header.pack(fill="x")
        self._header.pack_propagate(False)

        logo = _get_logo()
        if logo:
            self._logo_lbl = ctk.CTkLabel(self._header, text="", image=logo,
                                           fg_color="transparent")
            self._logo_lbl.pack(side="left", padx=16, pady=10)
        else:
            self._logo_lbl = ctk.CTkLabel(self._header, text="GQ Group  APS Parser",
                                           font=FONT_LOGO, text_color="white")
            self._logo_lbl.pack(side="left", padx=20, pady=12)

        self._header_step = ctk.CTkLabel(
            self._header, text="1 / 2",
            font=FONT_SMALL, text_color=TEXT_NAV_LIGHT
        )
        self._header_step.pack(side="right", padx=16)

        for w in [self._header, self._logo_lbl, self._header_step]:
            self._bind_drag(w)

    # ── Step 1: server + API key ──────────────────────────────────────────────
    def _build_step1(self):
        pad = PAD_XL
        self._frame1 = ctk.CTkFrame(self, fg_color="transparent")

        self._sub1 = ctk.CTkLabel(
            self._frame1, text=t("auth_subtitle"),
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, wraplength=420
        )
        self._sub1.pack(pady=(18, 0), padx=pad, anchor="w")

        ctk.CTkFrame(self._frame1, height=1, fg_color="#D5D8DC").pack(
            fill="x", padx=pad, pady=(14, 0))

        # Language selector
        lang_row = ctk.CTkFrame(self._frame1, fg_color="transparent")
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

        form = ctk.CTkFrame(self._frame1, fg_color="transparent")
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
                                       show="*", border_color=NAVY_LIGHT)
        self.key_entry.pack(side="left", fill="x", expand=True)
        if self.config.api_key:
            self.key_entry.insert(0, self.config.api_key)

        self._show_key = False
        self.eye_btn = ctk.CTkButton(
            key_row, text="👁", width=44, height=40,
            fg_color=NAVY_LIGHT, hover_color=BLUE_MID,
            command=self._toggle_eye, corner_radius=RADIUS_SM
        )
        self.eye_btn.pack(side="left", padx=(8, 0))

        self.status1_lbl = ctk.CTkLabel(self._frame1, text="", font=FONT_NORMAL,
                                         text_color=NAVY_LIGHT, wraplength=420)
        self.status1_lbl.pack(pady=(8, 0), padx=pad)

        self.connect_btn = ctk.CTkButton(
            self._frame1, text=t("auth_connect"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=48, corner_radius=RADIUS_MD,
            command=self._try_connect
        )
        self.connect_btn.pack(pady=16, padx=pad, fill="x")

        self.server_entry.bind("<Return>", lambda e: self.key_entry.focus())
        self.key_entry.bind("<Return>",    lambda e: self._try_connect())

    # ── Step 2: user dropdown + password ─────────────────────────────────────
    def _build_step2(self):
        pad = PAD_XL
        self._frame2 = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(
            self._frame2, text=t("auth_step2_title"),
            font=FONT_HEADING, text_color=NAVY
        ).pack(pady=(20, 4), padx=pad, anchor="w")

        ctk.CTkLabel(
            self._frame2, text=t("auth_step2_sub"),
            font=FONT_NORMAL, text_color=TEXT_SECONDARY, wraplength=420
        ).pack(pady=(0, 4), padx=pad, anchor="w")

        ctk.CTkFrame(self._frame2, height=1, fg_color="#D5D8DC").pack(
            fill="x", padx=pad, pady=(8, 0))

        form2 = ctk.CTkFrame(self._frame2, fg_color="transparent")
        form2.pack(pady=16, padx=pad, fill="x")

        # User dropdown
        ctk.CTkLabel(form2, text=t("auth_user_select"),
                     font=FONT_NORMAL, text_color=NAVY, anchor="w").pack(fill="x")

        self._combo_var = ctk.StringVar(value="")
        self._combo = ctk.CTkComboBox(
            form2, variable=self._combo_var,
            values=["..."], width=420, height=40, font=FONT_NORMAL,
            command=self._on_user_selected,
            state="readonly"
        )
        self._combo.pack(fill="x", pady=(4, 14))

        # Password
        ctk.CTkLabel(form2, text=t("auth_password"),
                     font=FONT_NORMAL, text_color=NAVY, anchor="w").pack(fill="x")
        pw_row = ctk.CTkFrame(form2, fg_color="transparent")
        pw_row.pack(fill="x", pady=(4, 0))
        self.password_entry = ctk.CTkEntry(
            pw_row, placeholder_text=t("auth_password_ph"),
            height=40, font=FONT_NORMAL, show="*", border_color=NAVY_LIGHT
        )
        self.password_entry.pack(side="left", fill="x", expand=True)

        self._show_pw = False
        self.pw_eye_btn = ctk.CTkButton(
            pw_row, text="👁", width=44, height=40,
            fg_color=NAVY_LIGHT, hover_color=BLUE_MID,
            command=self._toggle_pw_eye, corner_radius=RADIUS_SM
        )
        self.pw_eye_btn.pack(side="left", padx=(8, 0))

        self.status2_lbl = ctk.CTkLabel(self._frame2, text="", font=FONT_NORMAL,
                                         text_color=NAVY_LIGHT, wraplength=420)
        self.status2_lbl.pack(pady=(10, 0), padx=pad)

        btn_row = ctk.CTkFrame(self._frame2, fg_color="transparent")
        btn_row.pack(pady=16, padx=pad, fill="x")

        self.back_btn = ctk.CTkButton(
            btn_row, text=t("auth_back"),
            font=FONT_NORMAL, fg_color="#AEB6BF", hover_color="#7F8C8D",
            height=44, corner_radius=RADIUS_MD, width=110,
            command=lambda: self._show_step(1)
        )
        self.back_btn.pack(side="left")

        self.login_btn = ctk.CTkButton(
            btn_row, text=t("auth_login"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=44, corner_radius=RADIUS_MD,
            command=self._try_login
        )
        self.login_btn.pack(side="left", padx=(12, 0), fill="x", expand=True)

        self.password_entry.bind("<Return>", lambda e: self._try_login())

    # ── Navigation ────────────────────────────────────────────────────────────
    def _show_step(self, step: int):
        self._step = step
        self._frame1.pack_forget()
        self._frame2.pack_forget()
        if step == 1:
            self._frame1.pack(fill="both", expand=True)
            self._header_step.configure(text="1 / 2")
            self.server_entry.focus()
        else:
            self._frame2.pack(fill="both", expand=True)
            self._header_step.configure(text="2 / 2")
            if not self._users_loaded:
                self._load_users()
            self.password_entry.focus()

    # ── Step 1 logic ──────────────────────────────────────────────────────────
    def _on_lang_change(self):
        Lang.set(self.lang_var.get())
        self._sub1.configure(text=t("auth_subtitle"))
        self.server_lbl.configure(text=t("auth_server"))
        self.server_entry.configure(placeholder_text=t("auth_server_ph"))
        self.key_lbl.configure(text=t("auth_key"))
        self.key_entry.configure(placeholder_text=t("auth_key_ph"))
        self.connect_btn.configure(text=t("auth_connect"))

    def _toggle_eye(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "*")
        self.eye_btn.configure(text="🙈" if self._show_key else "👁")

    def _toggle_pw_eye(self):
        self._show_pw = not self._show_pw
        self.password_entry.configure(show="" if self._show_pw else "*")
        self.pw_eye_btn.configure(text="🙈" if self._show_pw else "👁")

    def _try_connect(self):
        server = self.server_entry.get().strip().rstrip("/")
        key    = self.key_entry.get().strip()
        if not server:
            self.status1_lbl.configure(text=t("auth_no_server"), text_color="#E74C3C")
            return
        if not key:
            self.status1_lbl.configure(text=t("auth_no_key"), text_color="#E74C3C")
            return

        self.connect_btn.configure(state="disabled",
                                   text="⏳  " + t("auth_checking"))
        self.status1_lbl.configure(text=t("auth_checking"), text_color=NAVY_LIGHT)

        self.config.server_url = server
        self.config.api_key    = key
        self.config.language   = self.lang_var.get()

        threading.Thread(target=self._check_thread, daemon=True).start()

    def _check_thread(self):
        try:
            ok, msg = self.api.validate_key()
        except Exception as e:
            ok, msg = False, str(e)
        self.after(0, lambda: self._on_connect_result(ok, msg))

    def _on_connect_result(self, ok: bool, msg: str):
        self.connect_btn.configure(state="normal", text=t("auth_connect"))
        if ok:
            self.config.save()
            self.status1_lbl.configure(text=t("auth_success"), text_color="#27AE60")
            self.after(400, lambda: self._show_step(2))
        else:
            err_key = "auth_invalid" if ("invalid" in msg or "403" in msg) else "auth_no_conn"
            self.status1_lbl.configure(text=t(err_key), text_color="#E74C3C")

    # ── Step 2 logic ──────────────────────────────────────────────────────────
    def _load_users(self):
        self._users_loaded = True
        self.status2_lbl.configure(text=t("auth_loading_users"), text_color=NAVY_LIGHT)
        threading.Thread(target=self._fetch_users_thread, daemon=True).start()

    def _fetch_users_thread(self):
        try:
            users = self.api.get_users_list()
            self.after(0, lambda: self._on_users_loaded(users))
        except Exception as e:
            self.after(0, lambda: self.status2_lbl.configure(
                text=str(e), text_color="#E74C3C"))

    def _on_users_loaded(self, users: list):
        self._users = users
        labels = [f"{u['full_name']}  ({u['username']})" for u in users]
        self._combo.configure(values=labels if labels else ["—"])
        if labels:
            # Pre-select last logged-in user; fall back to first in list
            last = self.config.last_username
            default = labels[0]
            if last:
                for lbl in labels:
                    if f"({last})" in lbl:
                        default = lbl
                        break
            self._combo.set(default)
        self.status2_lbl.configure(text="")

    def _on_user_selected(self, label: str):
        pass  # selection tracked via _combo_var

    def _get_username(self) -> str:
        label = self._combo_var.get()
        if label and label != "—":
            for u in self._users:
                if f"{u['full_name']}  ({u['username']})" == label:
                    return u["username"]
        return ""

    def _try_login(self):
        username = self._get_username()
        password = self.password_entry.get().strip()
        if not username:
            self.status2_lbl.configure(text=t("auth_no_user"), text_color="#E74C3C")
            return
        if not password:
            self.status2_lbl.configure(text=t("auth_no_password"), text_color="#E74C3C")
            return

        self.login_btn.configure(state="disabled",
                                 text="⏳  " + t("auth_checking"))
        self.status2_lbl.configure(text=t("auth_checking"), text_color=NAVY_LIGHT)

        threading.Thread(
            target=self._login_thread, args=(username, password), daemon=True
        ).start()

    def _login_thread(self, username: str, password: str):
        try:
            ok, msg, data = self.api.login(username, password)
        except Exception as e:
            ok, msg, data = False, str(e), {}
        self.after(0, lambda: self._on_login_result(ok, msg, data))

    def _on_login_result(self, ok: bool, msg: str, data: dict):
        self.login_btn.configure(state="normal", text=t("auth_login"))
        if ok:
            self.config.set_user(data)
            self.config.last_username = data.get("username", self.config.last_username)
            self.config.save()
            self.status2_lbl.configure(text=t("auth_success"), text_color="#27AE60")
            self.after(400, self._finish_ok)
        else:
            err_map = {
                "wrong_creds":   t("auth_wrong_creds"),
                "no_connection": t("auth_no_conn"),
            }
            self.status2_lbl.configure(
                text=err_map.get(msg, t("auth_login_failed")),
                text_color="#E74C3C")

    def _finish_ok(self):
        self.destroy()
        self.on_success()

    def _on_close(self):
        self.destroy()
        if self.on_cancel:
            self.on_cancel()
