"""
Страница управления пользователями — только для superadmin.
Показывает таблицу пользователей с возможностью:
  - Создать нового пользователя
  - Редактировать существующего (ФИО, email, телефон, роль, пароль, статус)
  - Деактивировать пользователя
"""
from __future__ import annotations

import threading
from typing import Optional, Callable

import customtkinter as ctk
from tkinter import ttk, messagebox

import requests

from assets.theme import *
from locales.strings import t
from services.api_service import ApiService


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _fmt_date(s: Optional[str]) -> str:
    if not s:
        return "—"
    return str(s)[:16].replace("T", " ")


# ── Диалог создания / редактирования пользователя ────────────────────────────

class UserDialog(ctk.CTkToplevel):
    """
    mode='create' — создание нового пользователя.
    mode='edit'   — редактирование существующего (передать user=dict).
    """
    def __init__(self, parent, api: ApiService,
                 mode: str = "create",
                 user: Optional[dict] = None,
                 roles: Optional[list] = None,
                 on_saved: Optional[Callable] = None):
        super().__init__(parent)
        self.api      = api
        self.mode     = mode
        self.user     = user or {}
        self.roles    = roles or []
        self.on_saved = on_saved

        title = (t("udlg_title_create") if mode == "create"
                 else t("udlg_title_edit", name=self.user.get("full_name", "")))
        self.title(title)
        self.configure(fg_color=BG_MAIN)
        self.resizable(False, False)

        W, H = 480, 560 if mode == "create" else 600
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        self.grab_set()
        self.lift()
        self.focus_force()

        self._build()

    # ── Построение формы ──────────────────────────────────────────────────────

    def _build(self):
        pad = PAD_LG

        # Заголовок
        hdr = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        icon = "➕" if self.mode == "create" else "✏️"
        lbl_text = (t("udlg_title_create") if self.mode == "create"
                    else t("udlg_title_edit", name=self.user.get("full_name", "")))
        ctk.CTkLabel(hdr, text=f"{icon}  {lbl_text}",
                     font=(*FONT_HEADING[:2], "bold"), text_color="white"
                     ).pack(side="left", padx=20, pady=12)

        # Форма
        form = ctk.CTkScrollableFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=pad, pady=(pad, 0))
        form.grid_columnconfigure(0, weight=1)

        def _field(parent, label_key: str, row: int,
                   placeholder: str = "", show: str = "",
                   initial: str = "") -> ctk.CTkEntry:
            ctk.CTkLabel(parent, text=t(label_key),
                         font=FONT_NORMAL, text_color=NAVY, anchor="w"
                         ).grid(row=row*2, column=0, sticky="w", pady=(10, 0))
            e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                              height=38, font=FONT_NORMAL,
                              show=show, border_color=NAVY_LIGHT)
            e.grid(row=row*2+1, column=0, sticky="ew", pady=(2, 0))
            if initial:
                e.insert(0, initial)
            return e

        # ФИО
        self.e_name = _field(form, "udlg_full_name", 0,
                              initial=self.user.get("full_name", ""))
        # Логин
        self.e_login = _field(form, "udlg_username", 1,
                               initial=self.user.get("username", ""))
        if self.mode == "edit":
            self.e_login.configure(state="disabled",
                                   fg_color="#F0F0F0", text_color=TEXT_SECONDARY)

        # Email
        self.e_email = _field(form, "udlg_email", 2,
                               placeholder="user@company.com",
                               initial=self.user.get("email", "") or "")
        # Телефон
        self.e_phone = _field(form, "udlg_phone", 3,
                               placeholder="+7 (777) 000-00-00",
                               initial=self.user.get("phone", "") or "")

        # Роль
        ctk.CTkLabel(form, text=t("udlg_role"),
                     font=FONT_NORMAL, text_color=NAVY, anchor="w"
                     ).grid(row=8, column=0, sticky="w", pady=(10, 0))
        role_labels  = [r["display_name"] for r in self.roles]
        role_values  = [r["name"]         for r in self.roles]
        current_role = self.user.get("role", "")
        try:
            cur_idx   = role_values.index(current_role)
            cur_label = role_labels[cur_idx]
        except (ValueError, IndexError):
            cur_label = role_labels[0] if role_labels else ""

        self._role_var = ctk.StringVar(value=cur_label)
        self.role_combo = ctk.CTkComboBox(
            form, variable=self._role_var,
            values=role_labels,
            height=38, font=FONT_NORMAL,
            border_color=NAVY_LIGHT,
            button_color=NAVY_LIGHT, button_hover_color=NAVY,
            dropdown_font=FONT_NORMAL,
            state="readonly",
        )
        self.role_combo.grid(row=9, column=0, sticky="ew", pady=(2, 0))
        self._role_labels = role_labels
        self._role_values = role_values

        # Сегмент
        SEG_LABELS = [t("seg_ss"), t("seg_os"), t("seg_sil")]
        SEG_VALUES = ["ss", "os", "sil"]
        ctk.CTkLabel(form, text=t("udlg_segment"),
                     font=FONT_NORMAL, text_color=NAVY, anchor="w"
                     ).grid(row=10, column=0, sticky="w", pady=(10, 0))
        cur_seg = self.user.get("segment", "ss") or "ss"
        try:
            cur_seg_label = SEG_LABELS[SEG_VALUES.index(cur_seg)]
        except (ValueError, IndexError):
            cur_seg_label = SEG_LABELS[0]
        self._seg_var = ctk.StringVar(value=cur_seg_label)
        self.seg_combo = ctk.CTkComboBox(
            form, variable=self._seg_var,
            values=SEG_LABELS,
            height=38, font=FONT_NORMAL,
            border_color=NAVY_LIGHT,
            button_color=NAVY_LIGHT, button_hover_color=NAVY,
            dropdown_font=FONT_NORMAL,
            state="readonly",
        )
        self.seg_combo.grid(row=11, column=0, sticky="ew", pady=(2, 0))
        self._seg_labels = SEG_LABELS
        self._seg_values = SEG_VALUES

        # Пароль
        pwd_key = "udlg_password" if self.mode == "create" else "udlg_password_edit"
        pwd_ph  = (t("udlg_password_ph_create") if self.mode == "create"
                   else t("udlg_password_ph_edit"))
        ctk.CTkLabel(form, text=t(pwd_key),
                     font=FONT_NORMAL, text_color=NAVY, anchor="w"
                     ).grid(row=12, column=0, sticky="w", pady=(10, 0))
        pwd_row = ctk.CTkFrame(form, fg_color="transparent")
        pwd_row.grid(row=13, column=0, sticky="ew", pady=(2, 0))
        pwd_row.grid_columnconfigure(0, weight=1)
        self.e_pwd = ctk.CTkEntry(pwd_row, placeholder_text=pwd_ph,
                                   height=38, font=FONT_NORMAL,
                                   show="•", border_color=NAVY_LIGHT)
        self.e_pwd.grid(row=0, column=0, sticky="ew")
        self._show_pwd = False
        ctk.CTkButton(pwd_row, text="👁", width=42, height=38,
                      fg_color=NAVY_LIGHT, hover_color=NAVY,
                      command=self._toggle_pwd, corner_radius=RADIUS_SM
                      ).grid(row=0, column=1, padx=(6, 0))

        # Статус (только при редактировании)
        if self.mode == "edit":
            self._active_var = ctk.BooleanVar(value=self.user.get("is_active", True))
            ctk.CTkCheckBox(form, text=t("udlg_active"),
                             variable=self._active_var,
                             font=FONT_NORMAL, text_color=NAVY,
                             fg_color=NAVY_LIGHT, hover_color=NAVY
                             ).grid(row=14, column=0, sticky="w", pady=(16, 0))
        else:
            self._active_var = None

        # Статус-строка ошибки
        self._status_lbl = ctk.CTkLabel(form, text="",
                                         font=FONT_NORMAL, text_color="#E74C3C",
                                         wraplength=400, anchor="w")
        self._status_lbl.grid(row=16, column=0, sticky="w", pady=(8, 0))

        # Кнопки
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=pad, pady=pad)
        btn_row.grid_columnconfigure(0, weight=1)

        self._save_btn = ctk.CTkButton(
            btn_row, text=t("udlg_save"),
            font=(*FONT_NORMAL[:2], "bold"),
            fg_color=NAVY, hover_color=NAVY_DARK,
            height=44, corner_radius=RADIUS_MD,
            command=self._submit
        )
        self._save_btn.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            btn_row, text=t("udlg_cancel"),
            font=FONT_NORMAL, fg_color="transparent",
            hover_color=BG_CARD, text_color=TEXT_SECONDARY,
            height=36, corner_radius=RADIUS_SM,
            border_width=1, border_color="#D5D8DC",
            command=self.destroy
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Enter → сохранить
        self.bind("<Return>", lambda e: self._submit())

    def _toggle_pwd(self):
        self._show_pwd = not self._show_pwd
        self.e_pwd.configure(show="" if self._show_pwd else "•")

    # ── Валидация и отправка ──────────────────────────────────────────────────

    def _get_role_value(self) -> str:
        label = self._role_var.get()
        try:
            return self._role_values[self._role_labels.index(label)]
        except (ValueError, IndexError):
            return ""

    def _get_segment_value(self) -> str:
        label = self._seg_var.get()
        try:
            return self._seg_values[self._seg_labels.index(label)]
        except (ValueError, IndexError):
            return "ss"

    def _submit(self):
        full_name = self.e_name.get().strip()
        username  = self.e_login.get().strip() if self.mode == "create" else self.user.get("username", "")
        email     = self.e_email.get().strip() or None
        phone     = self.e_phone.get().strip() or None
        password  = self.e_pwd.get()
        role      = self._get_role_value()
        segment   = self._get_segment_value()

        # Валидация
        if not full_name:
            self._status_lbl.configure(text=t("udlg_no_name"))
            return
        if self.mode == "create" and not username:
            self._status_lbl.configure(text=t("udlg_no_username"))
            return
        if not role:
            self._status_lbl.configure(text=t("udlg_no_role"))
            return
        if self.mode == "create" and not password:
            self._status_lbl.configure(text=t("udlg_no_password"))
            return
        if password and len(password) < 6:
            self._status_lbl.configure(text=t("udlg_pwd_too_short"))
            return

        self._save_btn.configure(state="disabled", text=t("udlg_saving"))
        self._status_lbl.configure(text="", text_color="#E74C3C")

        if self.mode == "create":
            data = {"full_name": full_name, "username": username,
                    "password": password, "role": role, "segment": segment,
                    "email": email, "phone": phone}
        else:
            data: dict = {"full_name": full_name, "role": role, "segment": segment,
                          "email": email, "phone": phone}
            if password:
                data["password"] = password
            if self._active_var is not None:
                data["is_active"] = self._active_var.get()

        threading.Thread(
            target=self._save_thread,
            args=(data,),
            daemon=True
        ).start()

    def _save_thread(self, data: dict):
        try:
            if self.mode == "create":
                result = self.api.create_user(data)
            else:
                result = self.api.update_user(self.user["id"], data)
            self.after(0, lambda: self._on_ok(result))
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            self.after(0, lambda: self._on_err(detail))
        except Exception as e:
            self.after(0, lambda: self._on_err(str(e)))

    def _on_ok(self, result: dict):
        if self.on_saved:
            self.on_saved(result, self.mode)
        self.destroy()

    def _on_err(self, detail: str):
        self._save_btn.configure(state="normal", text=t("udlg_save"))
        self._status_lbl.configure(text=f"❌  {detail}", text_color="#E74C3C")


# ── Страница пользователей ────────────────────────────────────────────────────

class UsersPage(ctk.CTkFrame):
    """Таблица пользователей + CRUD. Видна только суперадминистратору."""

    def __init__(self, parent, api: ApiService, app):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.api   = api
        self.app   = app
        self._users: list[dict] = []
        self._roles: list[dict] = []
        self._selected_user: Optional[dict] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build()

    # ── Построение UI ─────────────────────────────────────────────────────────

    def _build(self):
        pad = PAD_MD

        # ── Панель инструментов ──────────────────────────────────────────────
        toolbar = ctk.CTkFrame(self, fg_color=BG_CARD,
                                corner_radius=RADIUS_MD,
                                border_width=1, border_color="#E0E0E0")
        toolbar.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 6))
        toolbar.grid_columnconfigure(1, weight=1)

        self.title_lbl = ctk.CTkLabel(
            toolbar, text=t("users_title"),
            font=FONT_HEADING, text_color=NAVY, anchor="w"
        )
        self.title_lbl.grid(row=0, column=0, padx=16, pady=14, sticky="w")

        # Счётчик пользователей
        self._count_lbl = ctk.CTkLabel(
            toolbar, text="", font=FONT_SMALL, text_color=NAVY_LIGHT
        )
        self._count_lbl.grid(row=0, column=1, padx=8, sticky="w")

        btn_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=12, pady=8)

        self.refresh_btn = ctk.CTkButton(
            btn_frame, text=t("users_refresh"), font=FONT_SMALL,
            fg_color="#AEB6BF", hover_color="#7F8C8D", text_color="white",
            height=34, width=120, corner_radius=RADIUS_SM,
            command=self.load_users
        )
        self.refresh_btn.pack(side="left", padx=4)

        self.add_btn = ctk.CTkButton(
            btn_frame, text=t("users_add"),
            font=(*FONT_SMALL[:2], "bold"),
            fg_color=NAVY_LIGHT, hover_color=NAVY,
            height=34, width=130, corner_radius=RADIUS_SM,
            command=self._open_create
        )
        self.add_btn.pack(side="left", padx=4)

        self.edit_btn = ctk.CTkButton(
            btn_frame, text=t("users_edit"), font=FONT_SMALL,
            fg_color=BLUE_MID, hover_color=NAVY,
            height=34, width=130, corner_radius=RADIUS_SM,
            state="disabled",
            command=self._open_edit
        )
        self.edit_btn.pack(side="left", padx=4)

        self.del_btn = ctk.CTkButton(
            btn_frame, text=t("users_delete"), font=FONT_SMALL,
            fg_color="#C0392B", hover_color="#922B21", text_color="white",
            height=34, width=150, corner_radius=RADIUS_SM,
            state="disabled",
            command=self._delete_user
        )
        self.del_btn.pack(side="left", padx=4)

        # ── Таблица пользователей ────────────────────────────────────────────
        table_frame = ctk.CTkFrame(self, fg_color=BG_CARD,
                                    corner_radius=RADIUS_MD,
                                    border_width=1, border_color="#E0E0E0")
        table_frame.grid(row=1, column=0, sticky="nsew",
                          padx=pad, pady=(0, pad))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Users.Treeview",
            background=BG_CARD, fieldbackground=BG_CARD,
            rowheight=30, font=("Calibri", 12),
        )
        style.configure(
            "Users.Treeview.Heading",
            background=NAVY, foreground="white",
            font=("Calibri", 12, "bold"),
            relief="flat",
        )
        style.map("Users.Treeview",
                  background=[("selected", NAVY_LIGHT)],
                  foreground=[("selected", "white")])

        cols = ["full_name", "username", "role_display",
                "segment", "email", "phone", "active", "last_login"]
        self.tree = ttk.Treeview(table_frame, columns=cols,
                                  show="headings", style="Users.Treeview",
                                  selectmode="browse")

        hdrs = [
            (t("users_col_name"),       "full_name",    200),
            (t("users_col_login"),      "username",     120),
            (t("users_col_role"),       "role_display", 160),
            (t("users_col_segment"),    "segment",      130),
            (t("users_col_email"),      "email",        180),
            (t("users_col_phone"),      "phone",        140),
            (t("users_col_active"),     "active",        110),
            (t("users_col_last_login"), "last_login",   140),
        ]
        for hdr, col, width in hdrs:
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=width, minwidth=60)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                             command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal",
                             command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._open_edit())

        # Тег для неактивных
        self.tree.tag_configure("inactive", foreground="#999999")
        self.tree.tag_configure("active",   foreground=TEXT_PRIMARY)

        # Статус-строка
        self._status_lbl = ctk.CTkLabel(
            self, text=t("users_loading"), font=FONT_SMALL,
            text_color=TEXT_SECONDARY
        )
        self._status_lbl.grid(row=2, column=0, pady=(0, 4))

    # ── Загрузка данных ───────────────────────────────────────────────────────

    def load_users(self):
        """Перезагружает список пользователей и роли с сервера."""
        self._status_lbl.configure(text=t("users_loading"), text_color=TEXT_SECONDARY)
        self.refresh_btn.configure(state="disabled")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        try:
            users = self.api.get_users()
            roles = self._roles or self.api.get_roles()
            self.after(0, lambda: self._populate(users, roles))
        except Exception as e:
            self.after(0, lambda: self._status_lbl.configure(
                text=t("users_error", error=str(e)), text_color="#E74C3C"
            ))
            self.after(0, lambda: self.refresh_btn.configure(state="normal"))

    def _populate(self, users: list, roles: list):
        self._users = users
        self._roles = roles
        self._selected_user = None
        self.edit_btn.configure(state="disabled")
        self.del_btn.configure(state="disabled")

        self.tree.delete(*self.tree.get_children())
        for u in users:
            active_str = t("users_active") if u.get("is_active") else t("users_inactive")
            tag = "active" if u.get("is_active") else "inactive"
            seg_code  = u.get("segment", "ss") or "ss"
            seg_label = t(f"seg_{seg_code}") if seg_code in ("ss","os","sil") else seg_code
            self.tree.insert("", "end", iid=str(u["id"]), tags=(tag,),
                              values=(
                                  u.get("full_name", ""),
                                  u.get("username", ""),
                                  u.get("role_display", u.get("role", "")),
                                  seg_label,
                                  u.get("email", "") or "—",
                                  u.get("phone", "") or "—",
                                  active_str,
                                  _fmt_date(u.get("last_login_at")),
                              ))

        count = len(users)
        self._count_lbl.configure(text=f"Всего: {count}")
        self._status_lbl.configure(text="", text_color=TEXT_SECONDARY)
        self.refresh_btn.configure(state="normal")

    # ── Выбор строки ─────────────────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            self._selected_user = None
            self.edit_btn.configure(state="disabled")
            self.del_btn.configure(state="disabled")
            return
        uid = int(sel[0])
        self._selected_user = next((u for u in self._users if u["id"] == uid), None)
        can_delete = (self._selected_user is not None and
                      self._selected_user.get("is_active", True))
        self.edit_btn.configure(state="normal")
        self.del_btn.configure(
            state="normal" if can_delete else "disabled"
        )

    # ── Создание ─────────────────────────────────────────────────────────────

    def _open_create(self):
        if not self._roles:
            try:
                self._roles = self.api.get_roles()
            except Exception as e:
                messagebox.showerror("", t("users_error", error=str(e)))
                return
        UserDialog(
            self, self.api,
            mode="create", roles=self._roles,
            on_saved=self._after_save
        )

    # ── Редактирование ────────────────────────────────────────────────────────

    def _open_edit(self):
        if not self._selected_user:
            messagebox.showinfo("", t("users_select_to_edit"))
            return
        if not self._roles:
            try:
                self._roles = self.api.get_roles()
            except Exception as e:
                messagebox.showerror("", t("users_error", error=str(e)))
                return
        UserDialog(
            self, self.api,
            mode="edit", user=self._selected_user, roles=self._roles,
            on_saved=self._after_save
        )

    def _after_save(self, result: dict, mode: str):
        name = result.get("full_name", result.get("username", ""))
        if mode == "create":
            messagebox.showinfo("✅", t("users_created", name=name))
        else:
            messagebox.showinfo("✅", t("users_saved"))
        self.load_users()

    # ── Удаление (деактивация) ────────────────────────────────────────────────

    def _delete_user(self):
        if not self._selected_user:
            return
        name = self._selected_user.get("full_name", self._selected_user.get("username", ""))
        if not messagebox.askyesno(
            t("users_delete"),
            t("users_confirm_delete", name=name),
            icon="warning"
        ):
            return
        uid = self._selected_user["id"]
        self.del_btn.configure(state="disabled")
        threading.Thread(target=self._delete_thread, args=(uid, name), daemon=True).start()

    def _delete_thread(self, uid: int, name: str):
        try:
            self.api.delete_user(uid)
            self.after(0, lambda: self._on_deleted(name))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(
                "", t("users_error", error=str(e))
            ))
            self.after(0, lambda: self.del_btn.configure(state="normal"))

    def _on_deleted(self, name: str):
        messagebox.showinfo("✅", t("users_deleted", name=name))
        self.load_users()

    # ── refresh_lang ──────────────────────────────────────────────────────────

    def refresh_lang(self):
        self.title_lbl.configure(text=t("users_title"))
        self.refresh_btn.configure(text=t("users_refresh"))
        self.add_btn.configure(text=t("users_add"))
        self.edit_btn.configure(text=t("users_edit"))
        self.del_btn.configure(text=t("users_delete"))
