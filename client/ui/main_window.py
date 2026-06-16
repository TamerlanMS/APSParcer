import os
import customtkinter as ctk
from PIL import Image
import sys
import threading

from assets.theme import *
from locales.strings import Lang, t
from services.config import AppConfig
from services.api_service import ApiService
from ui.dialogs.auth_dialog import AuthDialog
from ui.pages.upload_page import UploadPage
from ui.pages.preview_page import PreviewPage
from ui.pages.database_page import DatabasePage
from ui.pages.users_page import UsersPage
from ui.pages.template_page import TemplatePage

try:
    from tkinterdnd2 import TkinterDnD
    _HAS_DND = True
except Exception:
    TkinterDnD = None
    _HAS_DND = False

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

NAV_W = 230
NAV_W_COLLAPSED = 56


class MainApp(ctk.CTk):
    def __init__(self, config: AppConfig):
        super().__init__()

        if _HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass

        self.config = config
        self.api    = ApiService(config)
        self._current_tab = 0
        self._nav_collapsed = False

        Lang.set(config.language)
        self.title(t("app_title"))
        self.geometry("1440x880")
        self.minsize(1100, 700)
        self.configure(fg_color=BG_MAIN)
        self.withdraw()

        try:
            self.iconbitmap("assets/icon.ico")
        except Exception:
            pass

        self._build_ui()
        self._switch_tab(0)

        if not config.is_configured:
            self._show_auth(first=True)
        else:
            self._validate_on_start()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _validate_on_start(self):
        def _check():
            ok, _ = self.api.validate_key()
            self.after(0, lambda: self._on_start_check(ok))
        threading.Thread(target=_check, daemon=True).start()

    def _on_start_check(self, ok: bool):
        self._show_auth(first=True, skip_to_login=ok)

    def _show_auth(self, first: bool = False, skip_to_login: bool = False):
        dlg = AuthDialog(
            self, self.config, self.api,
            on_success=self._on_auth_success,
            on_cancel=self._on_auth_cancel if first else None,
        )
        if skip_to_login:
            dlg.after(100, lambda: dlg._show_step(2))

    def _on_auth_success(self):
        Lang.set(self.config.language)
        try:
            self._refresh_all_labels()
            self._update_user_panel()
            self.database_page._apply_role_visibility()
        except Exception:
            import traceback; traceback.print_exc()
        finally:
            self._open_main()

    def _on_auth_cancel(self):
        sys.exit(0)

    def _open_main(self):
        self._update_statusbar()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _logout(self):
        threading.Thread(target=self.api.logout, daemon=True).start()
        self.withdraw()
        self._show_auth(first=True)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_nav()

        self.content_frame = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        self.upload_page   = UploadPage(self.content_frame, self.api, self)
        self.preview_page  = PreviewPage(self.content_frame, self.api, self)
        self.database_page = DatabasePage(self.content_frame, self.api, self)
        self.users_page    = UsersPage(self.content_frame, self.api, self)
        self.template_page = TemplatePage(self.content_frame, self.api, self)

        for page in [self.upload_page, self.preview_page,
                     self.database_page, self.users_page,
                     self.template_page]:
            page.grid(row=0, column=0, sticky="nsew")

        self.statusbar = ctk.CTkLabel(
            self, text="", font=FONT_SMALL,
            fg_color=NAVY_DARK, text_color=TEXT_NAV_LIGHT,
            anchor="w", corner_radius=0, height=22
        )
        self.statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._pages_built = True

    # ── Nav (pack-based для правильного layout) ───────────────────────────────

    # Icon-only text for each tab index (used when sidebar is collapsed)
    _NAV_ICON_ONLY = {0: "📄", 1: "📊", 2: "🗄", 3: "👥", 4: "📋"}

    def _build_nav(self):
        nav = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, width=NAV_W)
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)
        nav.pack_propagate(False)
        self.nav_frame = nav

        # ── Collapse toggle ────────────────────────────────────────────────────
        self._toggle_btn = ctk.CTkButton(
            nav, text="◀", font=("Calibri", 12), width=28, height=28,
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV_LIGHT, corner_radius=RADIUS_SM,
            command=self._toggle_nav,
        )
        self._toggle_btn.pack(anchor="e", padx=6, pady=(6, 0))

        # ── Logo ──────────────────────────────────────────────────────────────
        self._logo_frame = ctk.CTkFrame(nav, fg_color=NAVY_DARK, corner_radius=0)
        self._logo_frame.pack(fill="x")

        _logo_img = None
        try:
            _logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
            _pil = Image.open(os.path.normpath(_logo_path))
            _w, _h = _pil.size
            _scale = min((NAV_W - 32) / _w, 54 / _h)
            _logo_img = ctk.CTkImage(light_image=_pil, dark_image=_pil,
                                     size=(int(_w * _scale), int(_h * _scale)))
        except Exception:
            pass
        if _logo_img:
            self._logo_lbl = ctk.CTkLabel(self._logo_frame, text="", image=_logo_img,
                                           fg_color="transparent")
            self._logo_lbl.pack(pady=(14, 14))
        else:
            self._logo_lbl = ctk.CTkLabel(self._logo_frame, text="GQ",
                                           font=FONT_LOGO, text_color="white")
            self._logo_lbl.pack(pady=(16, 14))

        # ── Language button ────────────────────────────────────────────────────
        self.lang_btn = ctk.CTkButton(
            nav, text=t("lang_switch"), font=FONT_SMALL,
            fg_color=BLUE_MID, hover_color=NAVY_DARK, text_color="white",
            width=56, height=26, command=self._toggle_lang, corner_radius=RADIUS_SM,
        )
        self.lang_btn.pack(anchor="e", padx=16, pady=(10, 6))

        ctk.CTkFrame(nav, fg_color=BLUE_MID, height=1,
                     corner_radius=0).pack(fill="x", padx=12, pady=(0, 4))

        # ── Main nav buttons (locale strings already include emoji) ────────────
        self.nav_btns: list = []
        for label_key, idx in [("nav_upload", 0), ("nav_preview", 1), ("nav_database", 2)]:
            btn = ctk.CTkButton(
                nav, text=t(label_key), font=FONT_NAV,
                fg_color="transparent", hover_color=BLUE_MID,
                text_color=TEXT_NAV, anchor="w",
                height=50, corner_radius=0, border_width=0,
                command=lambda i=idx: self._switch_tab(i),
            )
            btn.pack(fill="x", padx=(16, 0))
            self.nav_btns.append((btn, label_key, idx))

        # ── Spacer ─────────────────────────────────────────────────────────────
        spacer = ctk.CTkFrame(nav, fg_color="transparent", corner_radius=0)
        spacer.pack(fill="both", expand=True)

        # ── Admin section ──────────────────────────────────────────────────────
        self._admin_container = ctk.CTkFrame(nav, fg_color="transparent", corner_radius=0)
        self._admin_container.pack(fill="x")

        self._admin_sep = ctk.CTkFrame(
            self._admin_container, fg_color=BLUE_MID, height=1, corner_radius=0)
        self._admin_lbl = ctk.CTkLabel(
            self._admin_container, text="  АДМИНИСТРИРОВАНИЕ",
            font=("Calibri", 9), text_color=TEXT_NAV, anchor="w")
        self._users_btn = ctk.CTkButton(
            self._admin_container,
            text=t("nav_users"), font=FONT_NAV,
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV, anchor="w",
            height=50, corner_radius=0, border_width=0,
            command=lambda: self._switch_tab(3),
        )
        self.nav_btns.append((self._users_btn, "nav_users", 3))

        self._template_btn = ctk.CTkButton(
            self._admin_container,
            text=t("nav_template"), font=FONT_NAV,
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV, anchor="w",
            height=50, corner_radius=0, border_width=0,
            command=lambda: self._switch_tab(4),
        )
        self.nav_btns.append((self._template_btn, "nav_template", 4))

        # ── User card ─────────────────────────────────────────────────────────
        self._user_card = ctk.CTkFrame(nav, fg_color=NAVY_DARK, corner_radius=8)
        self._user_card.pack(fill="x", padx=10, pady=(4, 4))

        name_row = ctk.CTkFrame(self._user_card, fg_color="transparent")
        name_row.pack(fill="x", padx=10, pady=(10, 2))
        ctk.CTkLabel(name_row, text="👤",
                     font=("Segoe UI Emoji", 13)).pack(side="left")
        self._user_name_lbl = ctk.CTkLabel(
            name_row, text="",
            font=(*FONT_SMALL[:2], "bold"), text_color="white",
            anchor="w", wraplength=160,
        )
        self._user_name_lbl.pack(side="left", padx=(6, 0))

        self._user_role_lbl = ctk.CTkLabel(
            self._user_card, text="",
            font=("Calibri", 10), text_color=TEXT_NAV_LIGHT, anchor="w",
        )
        self._user_role_lbl.pack(fill="x", padx=10, pady=(0, 8))

        # ── Logout / Change key ────────────────────────────────────────────────
        self.logout_btn = ctk.CTkButton(
            nav, text=t("nav_logout"), font=FONT_SMALL,
            fg_color="transparent", hover_color="#922B21",
            text_color=TEXT_NAV_LIGHT, height=30,
            border_width=1, border_color=BLUE_MID,
            corner_radius=RADIUS_SM, command=self._logout,
        )
        self.logout_btn.pack(fill="x", padx=14, pady=(4, 2))

        self.change_key_btn = ctk.CTkButton(
            nav, text=t("nav_change_key"), font=("Calibri", 10),
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV, height=24, border_width=0,
            corner_radius=RADIUS_SM,
            command=lambda: self._show_auth(first=False),
        )
        self.change_key_btn.pack(fill="x", padx=14, pady=(0, 12))

        self._update_user_panel()

    def _toggle_nav(self):
        self._nav_collapsed = not self._nav_collapsed

        if self._nav_collapsed:
            # ── Collapse to icon strip ─────────────────────────────────────────
            self.nav_frame.configure(width=NAV_W_COLLAPSED)
            self._toggle_btn.configure(text="▶")

            # Hide text-heavy widgets
            self._logo_frame.pack_forget()
            self.lang_btn.pack_forget()
            self._user_card.pack_forget()
            self.logout_btn.pack_forget()
            self.change_key_btn.pack_forget()
            self._admin_sep.pack_forget()
            self._admin_lbl.pack_forget()

            # Shrink nav buttons to square icon-only
            for btn, key, idx in self.nav_btns:
                icon = self._NAV_ICON_ONLY.get(idx, "•")
                btn.configure(
                    text=icon, anchor="center",
                    font=("Segoe UI Emoji", 18),
                    width=NAV_W_COLLAPSED, height=NAV_W_COLLAPSED,
                )
                btn.pack_configure(padx=0)
        else:
            # ── Expand to full panel ───────────────────────────────────────────
            self.nav_frame.configure(width=NAV_W)
            self._toggle_btn.configure(text="◀")

            # Restore logo (pack before toggle button is tricky — repack all)
            self._logo_frame.pack(fill="x", after=self._toggle_btn)
            self.lang_btn.pack(anchor="e", padx=16, pady=(10, 6))
            self._user_card.pack(fill="x", padx=10, pady=(4, 4))
            self.logout_btn.pack(fill="x", padx=14, pady=(4, 2))
            self.change_key_btn.pack(fill="x", padx=14, pady=(0, 12))

            # Restore nav buttons
            for btn, key, idx in self.nav_btns:
                btn.configure(
                    text=t(key), anchor="w",
                    font=FONT_NAV,
                    width=0, height=50,
                )
                btn.pack_configure(padx=(16, 0))

            self._update_user_panel()  # restores admin section
    def _update_user_panel(self):
        if self.config.is_logged_in:
            name = self.config.user_full_name or self.config.user_username
            self._user_name_lbl.configure(text=name)
            role_map = {
                "superadmin": "Суперадминистратор",
                "admin":      "Администратор",
                "user":       "Пользователь",
                "viewer":     "Просмотр",
            }
            self._user_role_lbl.configure(
                text=role_map.get(self.config.user_role, self.config.user_role)
            )
        else:
            self._user_name_lbl.configure(text="—")
            self._user_role_lbl.configure(text="")

        is_super = (self.config.user_role == "superadmin")
        is_admin_up = self.config.user_role in ("superadmin", "administrator")
        if is_admin_up:
            # Показываем admin-секцию
            self._admin_sep.pack(fill="x", padx=14, pady=(6, 0))
            self._admin_lbl.pack(fill="x", padx=4, pady=(4, 0))
            if is_super:
                self._users_btn.pack(fill="x")
            else:
                self._users_btn.pack_forget()
            self._template_btn.pack(fill="x")
        else:
            # Скрываем admin-секцию
            self._admin_sep.pack_forget()
            self._admin_lbl.pack_forget()
            self._users_btn.pack_forget()
            self._template_btn.pack_forget()
            if self._current_tab in (3, 4):
                self._switch_tab(0)

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _switch_tab(self, index: int):
        self._current_tab = index
        pages = [self.upload_page, self.preview_page,
                 self.database_page, self.users_page, self.template_page]
        for i, page in enumerate(pages):
            page.lift() if i == index else page.lower()

        for btn, key, btn_idx in self.nav_btns:
            if btn_idx == index:
                btn.configure(fg_color=BLUE_MID, text_color="white",
                               font=(*FONT_NAV[:2], "bold"))
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_NAV,
                               font=FONT_NAV)

        if index == 3 and self.config.user_role == "superadmin":
            self.users_page.load_users()
        if index == 4 and self.config.user_role in ("superadmin", "administrator"):
            self.template_page.load()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def on_result_ready(self, result: dict):
        self.preview_page.load_data(result)
        self._switch_tab(1)
        stats = result.get("stats", {})
        total = result.get("total", 0)
        self.statusbar.configure(
            text=f"  {t('preview_stat', total=total, exact=stats.get('exact', 0), warn=stats.get('multiple', 0) + stats.get('fuzzy', 0), nf=stats.get('not_found', 0))}"
        )

    def _update_statusbar(self):
        if not self.config.is_configured:
            self.statusbar.configure(text=f"  {t('status_not_conn')}")
        elif self.config.is_logged_in:
            self.statusbar.configure(
                text=f"  {t('status_user', url=self.config.server_url, name=self.config.user_full_name or self.config.user_username, role=self.config.user_role)}"
            )
        else:
            self.statusbar.configure(
                text=f"  {t('status_connected', url=self.config.server_url)}"
            )

    # ── Language ──────────────────────────────────────────────────────────────

    def _toggle_lang(self):
        new_lang = "kz" if Lang.get() == "ru" else "ru"
        Lang.set(new_lang)
        self.config.language = new_lang
        self.config.save()
        self._refresh_all_labels()

    def _refresh_all_labels(self):
        self.title(t("app_title"))
        self.lang_btn.configure(text=t("lang_switch"))
        self.change_key_btn.configure(text=t("nav_change_key"))
        self.logout_btn.configure(text=t("nav_logout"))
        self._update_user_panel()
        if not self._nav_collapsed:
            for btn, key, idx in self.nav_btns:
                btn.configure(text=t(key))
        self._switch_tab(self._current_tab)   # восстановить активный стиль
        self.upload_page.refresh_lang()
        self.preview_page.refresh_lang()
        self.database_page.refresh_lang()
        self.users_page.refresh_lang()
        self.template_page.refresh_lang()
        self._update_statusbar()
