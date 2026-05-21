import customtkinter as ctk
from tkinter import messagebox
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

# tkinterdnd2 поверх CTk: корневое окно должно регистрировать DnD сразу,
# иначе drop_target_register на дочерних виджетах молча не сработает.
try:
    from tkinterdnd2 import TkinterDnD
    _HAS_DND = True
except Exception:
    TkinterDnD = None
    _HAS_DND = False


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class MainApp(ctk.CTk):
    def __init__(self, config: AppConfig):
        super().__init__()

        # Активируем drag-and-drop ДО создания дочерних виджетов.
        # Без этого вызова drop_target_register("DND_Files") будет no-op.
        if _HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass
        self.config = config
        self.api    = ApiService(config)

        Lang.set(config.language)

        self.title(t("app_title"))
        self.geometry("1400x860")
        self.minsize(1100, 700)
        self.configure(fg_color=BG_MAIN)

        # Скрываем главное окно пока идёт авторизация
        self.withdraw()

        try:
            self.iconbitmap("assets/icon.ico")
        except Exception:
            pass

        # Строим UI сразу (скрытым)
        self._build_ui()
        self._switch_tab(0)

        # Авторизация
        if not config.is_configured:
            # Первый запуск — показываем диалог
            self._show_auth(first=True)
        else:
            # Есть сохранённый ключ — проверяем асинхронно
            self._validate_on_start()

    # ── Auth ─────────────────────────────────────────────────────────────────
    def _validate_on_start(self):
        """Асинхронная проверка сохранённого ключа — не блокирует UI."""
        def _check():
            ok, msg = self.api.validate_key()
            self.after(0, lambda: self._on_start_check(ok))
        threading.Thread(target=_check, daemon=True).start()

    def _on_start_check(self, ok: bool):
        if ok:
            self._open_main()
        else:
            self._show_auth(first=True)

    def _show_auth(self, first: bool = False):
        AuthDialog(
            self, self.config, self.api,
            on_success=self._on_auth_success,
            on_cancel=self._on_auth_cancel if first else None,
        )

    def _on_auth_success(self):
        Lang.set(self.config.language)
        self._refresh_all_labels()
        self._open_main()

    def _on_auth_cancel(self):
        sys.exit(0)

    def _open_main(self):
        self._update_statusbar()
        self.deiconify()
        self.lift()
        self.focus_force()

    # ── UI ───────────────────────────────────────────────────────────────────
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

        for page in [self.upload_page, self.preview_page, self.database_page]:
            page.grid(row=0, column=0, sticky="nsew")

        self.statusbar = ctk.CTkLabel(
            self, text="", font=FONT_SMALL,
            fg_color=NAVY, text_color=TEXT_NAV_LIGHT,
            anchor="w", corner_radius=0, height=24
        )
        self.statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._pages_built = True

    def _build_nav(self):
        nav = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, width=220)
        nav.grid(row=0, column=0, sticky="nsew")
        nav.grid_propagate(False)
        nav.grid_rowconfigure(10, weight=1)

        logo_frame = ctk.CTkFrame(nav, fg_color=NAVY_DARK, corner_radius=0)
        logo_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(logo_frame, text="APS Parser", font=FONT_LOGO,
                     text_color="white").pack(pady=(18, 2))
        ctk.CTkLabel(logo_frame, text=t("app_subtitle"), font=FONT_SMALL,
                     text_color=TEXT_NAV_LIGHT).pack(pady=(0, 14))

        self.lang_btn = ctk.CTkButton(
            nav, text=t("lang_switch"), font=FONT_SMALL,
            fg_color=BLUE_MID, hover_color=NAVY_LIGHT,
            text_color="white", width=60, height=26,
            command=self._toggle_lang, corner_radius=RADIUS_SM
        )
        self.lang_btn.grid(row=1, column=0, pady=(0, 12), padx=16, sticky="e")

        self.nav_btns = []
        for key, idx in [("nav_upload", 0), ("nav_preview", 1), ("nav_database", 2)]:
            btn = ctk.CTkButton(
                nav, text=t(key), font=FONT_NAV,
                fg_color="transparent", hover_color=BLUE_MID,
                text_color=TEXT_NAV, anchor="w",
                height=52, corner_radius=0, border_width=0,
                command=lambda i=idx: self._switch_tab(i)
            )
            btn.grid(row=2 + idx, column=0, sticky="ew")
            self.nav_btns.append((btn, key))

        ctk.CTkFrame(nav, fg_color="transparent").grid(row=10, column=0, sticky="nsew")

        key_short = self.config.api_key[-8:] if self.config.api_key else "—"
        self.key_label = ctk.CTkLabel(
            nav, text=f"{t('nav_key_info')}...{key_short}",
            font=FONT_SMALL, text_color=TEXT_NAV_LIGHT
        )
        self.key_label.grid(row=11, column=0, pady=(0, 4))

        self.change_key_btn = ctk.CTkButton(
            nav, text=t("nav_change_key"), font=FONT_SMALL,
            fg_color="transparent", hover_color=BLUE_MID,
            text_color=TEXT_NAV_LIGHT, height=32,
            border_width=1, border_color=NAVY_LIGHT,
            corner_radius=RADIUS_SM,
            command=lambda: self._show_auth(first=False)
        )
        self.change_key_btn.grid(row=12, column=0, padx=16, pady=(0, 16), sticky="ew")

        self.nav_frame = nav

    def _switch_tab(self, index: int):
        pages = [self.upload_page, self.preview_page, self.database_page]
        for i, page in enumerate(pages):
            page.lift() if i == index else page.lower()

        for i, (btn, key) in enumerate(self.nav_btns):
            if i == index:
                btn.configure(fg_color=NAVY_LIGHT, text_color="white",
                              font=(*FONT_NAV[:2], "bold"))
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_NAV,
                              font=FONT_NAV)

    def on_result_ready(self, result: dict):
        self.preview_page.load_data(result)
        self._switch_tab(1)
        stats = result.get("stats", {})
        total = result.get("total", 0)
        self.statusbar.configure(
            text=f"  {t('preview_stat', total=total, exact=stats.get('exact', 0), warn=stats.get('multiple', 0) + stats.get('fuzzy', 0), nf=stats.get('not_found', 0))}"
        )

    def _update_statusbar(self):
        if self.config.is_configured:
            self.statusbar.configure(
                text=f"  {t('status_connected', url=self.config.server_url)}"
            )
        else:
            self.statusbar.configure(text=f"  {t('status_not_conn')}")

    def _toggle_lang(self):
        Lang.set(new_lang)
        self.config.language = new_lang
        self.config.save()
        self._refresh_all_labels()

    def _refresh_all_labels(self):
        self.title(t("app_title"))
        self.lang_btn.configure(text=t("lang_switch"))
        self.change_key_btn.configure(text=t("nav_change_key"))
        key_short = self.config.api_key[-8:] if self.config.api_key else "—"
        self.key_label.configure(text=f"{t('nav_key_info')}...{key_short}")
        for btn, key in self.nav_btns:
            btn.configure(text=t(key))
        self.upload_page.refresh_lang()
        self.preview_page.refresh_lang()
        self.database_page.refresh_lang()
        self._update_statusbar()
