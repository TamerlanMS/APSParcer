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
from ui.pages.analytics_page import AnalyticsPage

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
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        print(f"[AUTH] logged in: role={self.config.user_role!r} segment={self.config.user_segment!r}")
        try:
            self._refresh_all_labels()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self._update_user_panel()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self.database_page._apply_role_visibility()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self.upload_page.on_login()
        except Exception:
            import traceback; traceback.print_exc()
        self._open_main()

    def _on_auth_cancel(self):
        sys.exit(0)

    def _on_close(self):
        """Сохраняем позицию/размер окна перед выходом."""
        try:
            state = self.state()
            if state == "zoomed":
                self.config.window_geometry = "zoomed"
            else:
                self.config.window_geometry = self.wm_geometry()
            self.config.save()
        except Exception:
            pass
        self.destroy()

    def _open_main(self):
        self._update_statusbar()
        self.deiconify()
        # Восстановить сохранённую позицию/размер
        geo = self.config.window_geometry
        if geo == "zoomed":
            self.after(50, lambda: self.state("zoomed"))
        elif geo:
            self.after(50, lambda: self.geometry(geo))
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

        self.upload_page    = UploadPage(self.content_frame, self.api, self)
        self.preview_page   = PreviewPage(self.content_frame, self.api, self)
        self.database_page  = DatabasePage(self.content_frame, self.api, self)
        self.users_page     = UsersPage(self.content_frame, self.api, self)
        self.template_page  = TemplatePage(self.content_frame, self.api, self)
        self.analytics_page = AnalyticsPage(self.content_frame, self.api, self)

        for page in [self.upload_page, self.preview_page,
                     self.database_page, self.users_page,
                     self.template_page, self.analytics_page]:
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
    _NAV_ICON_ONLY = {0: "📄", 1: "📊", 2: "🗄", 3: "👥", 4: "📋", 5: "📈"}

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
            if idx == 2:
                self._db_nav_btn = btn  # ссылка для скрытия у директора

        # ── Аналитика (director + admin, скрыта по умолчанию) ─────────────────
        self._analytics_nav_btn = ctk.CTkButton(
            nav, text=t("nav_analytics"), font=FONT_NAV,
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV, anchor="w",
            height=50, corner_radius=0, border_width=0,
            command=lambda: self._switch_tab(5),
        )
        self.nav_btns.append((self._analytics_nav_btn, "nav_analytics", 5))
        # Видимость управляется в _update_user_panel (director + admin)

        # ── Project tabs panel (shown when multi-PDF files are loaded) ─────────
        self._tab_panel = ctk.CTkFrame(nav, fg_color=NAVY_DARK, corner_radius=0)
        # Not packed here — shown dynamically via show_project_tabs()

        self._tab_inner = ctk.CTkScrollableFrame(
            self._tab_panel,
            fg_color="transparent", corner_radius=0,
            height=110,
            scrollbar_button_color=BLUE_MID,
            scrollbar_button_hover_color=NAVY_DARK,
        )
        self._tab_inner.pack(fill="x", padx=0, pady=(2, 0))

        self._save_all_btn = ctk.CTkButton(
            self._tab_panel,
            text="💾 Сохранить Excel всех",
            font=FONT_SMALL,
            fg_color=NAVY_LIGHT, hover_color=NAVY_DARK,
            text_color="white",
            height=32, corner_radius=0,
            command=lambda: self.preview_page.save_all_excel(),
        )
        self._save_all_btn.pack(fill="x", padx=4, pady=(2, 6))

        self._project_tab_btns: list = []
        self._tabs_visible: bool = False

        # ── Spacer ─────────────────────────────────────────────────────────────
        spacer = ctk.CTkFrame(nav, fg_color="transparent", corner_radius=0)
        spacer.pack(fill="both", expand=True)

        # ── Admin section ──────────────────────────────────────────────────────
        self._admin_container = ctk.CTkFrame(nav, fg_color="transparent", corner_radius=0)
        # пакуется позже (side="bottom") после user_card и кнопок

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
        self.change_key_btn = ctk.CTkButton(
            nav, text=t("nav_change_key"), font=("Calibri", 10),
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV, height=24, border_width=0,
            corner_radius=RADIUS_SM,
            command=lambda: self._show_auth(first=False),
        )
        self.change_key_btn.pack(fill="x", padx=14, pady=(0, 12), side="bottom")

        self.logout_btn = ctk.CTkButton(
            nav, text=t("nav_logout"), font=FONT_SMALL,
            fg_color="transparent", hover_color="#922B21",
            text_color=TEXT_NAV_LIGHT, height=30,
            border_width=1, border_color=BLUE_MID,
            corner_radius=RADIUS_SM, command=self._logout,
        )
        self.logout_btn.pack(fill="x", padx=14, pady=(4, 2), side="bottom")

        self._user_card = ctk.CTkFrame(nav, fg_color=NAVY_DARK, corner_radius=8)
        self._user_card.pack(fill="x", padx=10, pady=(4, 4), side="bottom")

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

        self._admin_container.pack(fill="x", side="bottom")

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
            if hasattr(self, "_tab_panel") and self._tabs_visible:
                self._tab_panel.pack_forget()
            self.logout_btn.pack_forget()
            self.change_key_btn.pack_forget()
            self._user_card.pack_forget()
            self._admin_container.pack_forget()
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
            # Restore project tabs panel if it was visible
            if hasattr(self, "_tab_panel") and self._tabs_visible:
                preview_btn = next((b for b, k, i in self.nav_btns if i == 1), None)
                if preview_btn:
                    self._tab_panel.pack(fill="x", after=preview_btn)
                else:
                    self._tab_panel.pack(fill="x")
            self.lang_btn.pack(anchor="e", padx=16, pady=(10, 6),
                               after=self._logo_frame)
            # Re-pack bottom section (side="bottom", порядок снизу вверх)
            self.change_key_btn.pack(fill="x", padx=14, pady=(0, 12), side="bottom")
            self.logout_btn.pack(fill="x", padx=14, pady=(4, 2), side="bottom")
            self._user_card.pack(fill="x", padx=10, pady=(4, 4), side="bottom")
            self._admin_container.pack(fill="x", side="bottom")

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
            # Показываем admin-секцию (сброс порядка после collapse/expand)
            self._admin_sep.pack_forget()
            self._admin_lbl.pack_forget()
            self._users_btn.pack_forget()
            self._template_btn.pack_forget()
            self._admin_sep.pack(fill="x", padx=14, pady=(6, 0))
            self._admin_lbl.pack(fill="x", padx=4, pady=(4, 0))
            if is_super:
                self._users_btn.pack(fill="x")
            self._template_btn.pack(fill="x")
        else:
            # Скрываем admin-секцию
            self._admin_sep.pack_forget()
            self._admin_lbl.pack_forget()
            self._users_btn.pack_forget()
            self._template_btn.pack_forget()
            if self._current_tab in (3, 4):
                self._switch_tab(0)

        # Кнопка "Аналитика" видна только director + admin
        is_analytics_user = self.config.user_role in (
            "superadmin", "administrator", "director"
        )
        if hasattr(self, "_analytics_nav_btn"):
            if is_analytics_user:
                if not self._analytics_nav_btn.winfo_ismapped():
                    # after= ставит кнопку прямо под "База данных"
                    self._analytics_nav_btn.pack(
                        fill="x", padx=(16, 0), after=self._db_nav_btn
                    )
            else:
                self._analytics_nav_btn.pack_forget()
                if self._current_tab == 5:
                    self._switch_tab(0)

        # Кнопка "База данных" скрыта для директора
        is_director = (self.config.user_role == "director")
        if hasattr(self, "_db_nav_btn"):
            if is_director:
                self._db_nav_btn.pack_forget()
                if self._current_tab == 2:
                    self._switch_tab(0)
            else:
                # Показываем — восстанавливаем позицию после "Предпросмотр"
                preview_btn = None
                for btn, key, idx in self.nav_btns:
                    if idx == 1:
                        preview_btn = btn
                        break
                if preview_btn and not self._db_nav_btn.winfo_ismapped():
                    self._db_nav_btn.pack(fill="x", padx=(16, 0),
                                          after=preview_btn)

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _switch_tab(self, index: int):
        self._current_tab = index
        pages = [self.upload_page, self.preview_page,
                 self.database_page, self.users_page,
                 self.template_page, self.analytics_page]
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
        if index == 5:
            self.analytics_page.load()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def show_project_tabs(self, names: list):
        """Populate and show the scrollable project-tab panel in the nav."""
        for btn in self._project_tab_btns:
            try:
                btn.destroy()
            except Exception:
                pass
        self._project_tab_btns.clear()

        for idx, name in enumerate(names):
            label = name if len(name) <= 22 else name[:20] + "\u2026"
            btn = ctk.CTkButton(
                self._tab_inner,
                text=f"\U0001f4c4 {label}",
                font=FONT_SMALL, anchor="w",
                fg_color=BLUE_MID if idx == 0 else "transparent",
                hover_color=BLUE_MID,
                text_color="white",
                height=28, corner_radius=RADIUS_SM,
                command=lambda i=idx: self._on_project_tab_click(i),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self._project_tab_btns.append(btn)

        # Insert panel after the 'Preview' nav button
        preview_btn = next((b for b, k, i in self.nav_btns if i == 1), None)
        if preview_btn:
            self._tab_panel.pack(fill="x", after=preview_btn)
        else:
            self._tab_panel.pack(fill="x")
        self._tabs_visible = True

    def hide_project_tabs(self):
        """Hide and clear the project-tab panel."""
        self._tab_panel.pack_forget()
        for btn in self._project_tab_btns:
            try:
                btn.destroy()
            except Exception:
                pass
        self._project_tab_btns.clear()
        self._tabs_visible = False

    def _on_project_tab_click(self, idx: int):
        """Handle a project-tab button click in the nav."""
        self._switch_project_tab_style(idx)
        self.preview_page.switch_project(idx)
        self._switch_tab(1)

    def _switch_project_tab_style(self, idx: int):
        """Highlight the active project tab and dim the others."""
        for i, btn in enumerate(self._project_tab_btns):
            try:
                btn.configure(fg_color=BLUE_MID if i == idx else "transparent")
            except Exception:
                pass

    def on_multi_result_ready(self, results: list):
        """Called by UploadPage when multiple PDF files finish processing."""
        self.preview_page.load_multi_data(results)
        self._switch_tab(1)
        total     = sum(r.get("total", 0) for r in results if r)
        exact     = sum(r.get("stats", {}).get("exact",    0) for r in results if r)
        warn      = sum(r.get("stats", {}).get("multiple", 0)
                       + r.get("stats", {}).get("fuzzy",   0) for r in results if r)
        nf        = sum(r.get("stats", {}).get("not_found",0) for r in results if r)
        from locales.strings import t
        self.statusbar.configure(
            text=f"  {t('preview_stat', total=total, exact=exact, warn=warn, nf=nf)}"
        )


    def open_spec_selection(self, result: dict):
        """Открывает предпросмотр в режиме подбора по спецификации Excel."""
        if hasattr(self, "_tabs_visible") and self._tabs_visible:
            self.hide_project_tabs()
        self.preview_page.load_spec_data(result)
        self._switch_tab(1)
        stats = result.get("stats", {}) or {}
        total = result.get("total", 0)
        self.statusbar.configure(
            text=(f"  Подбор по спецификации: {total} позиций  |  "
                  f"найдено точно: {stats.get('exact', 0)}, "
                  f"требует проверки: {stats.get('multiple', 0) + stats.get('fuzzy', 0)}, "
                  f"не найдено: {stats.get('not_found', 0)}")
        )

    def on_result_ready(self, result: dict):
        if hasattr(self, "_tabs_visible") and self._tabs_visible:
            self.hide_project_tabs()
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
