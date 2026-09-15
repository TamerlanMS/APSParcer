"""
Горячие клавиши буфера обмена во всех полях ввода приложения.

Проблема: стандартные привязки Tk (<<Paste>>, <Control-v>) срабатывают по
символу, а не по физической клавише. При русской раскладке Ctrl+V даёт символ
«м», события <Control-v> не возникает — и вставка не работает. То же с Ctrl+C,
Ctrl+X и Ctrl+A.

Решение: перехватываем <Control-KeyPress> на уровне класса виджета и смотрим
на event.keycode — код физической клавиши от раскладки не зависит.
Привязка через bind_class действует на ВСЕ поля ввода, включая создаваемые
позже (CTkEntry внутри использует обычный tk.Entry).

Применение — один раз при старте приложения:

    from ui.clipboard_fix import enable_clipboard_shortcuts
    enable_clipboard_shortcuts(root)
"""
from locales.strings import t
import logging

logger = logging.getLogger(__name__)

# Коды физических клавиш (одинаковы для Windows и X11 для этих букв)
KEY_A = 65
KEY_C = 67
KEY_V = 86
KEY_X = 88

# Классы виджетов, к которым применяем привязки
_TEXT_CLASSES  = ("Entry", "TEntry", "Text", "ScrolledText")
_TREE_CLASSES  = ("Treeview",)


def _widget_is_readonly(w) -> bool:
    try:
        state = str(w.cget("state"))
    except Exception:
        return False
    return state in ("disabled", "readonly")


def _do_paste(event):
    w = event.widget
    if _widget_is_readonly(w):
        return "break"
    try:
        text = w.clipboard_get()
    except Exception:
        return "break"          # буфер пуст или содержит не текст
    if not text:
        return "break"
    # Многострочный текст в однострочное поле — схлопываем в одну строку
    if not _is_multiline(w):
        text = " ".join(text.split())
    try:
        if w.selection_present():
            w.delete("sel.first", "sel.last")
    except Exception:
        pass
    try:
        w.insert("insert", text)
    except Exception:
        return "break"
    return "break"


def _is_multiline(w) -> bool:
    return w.winfo_class() in ("Text", "ScrolledText")


def _selected_text(w):
    try:
        if _is_multiline(w):
            return w.get("sel.first", "sel.last")
        if w.selection_present():
            return w.selection_get()
    except Exception:
        pass
    return ""


def _do_copy(event):
    w = event.widget
    text = _selected_text(w)
    if not text:
        return "break"
    try:
        w.clipboard_clear()
        w.clipboard_append(text)
    except Exception:
        pass
    return "break"


def _do_cut(event):
    w = event.widget
    if _widget_is_readonly(w):
        return "break"
    text = _selected_text(w)
    if not text:
        return "break"
    try:
        w.clipboard_clear()
        w.clipboard_append(text)
        w.delete("sel.first", "sel.last")
    except Exception:
        pass
    return "break"


def _do_select_all(event):
    w = event.widget
    try:
        if _is_multiline(w):
            w.tag_add("sel", "1.0", "end-1c")
            w.mark_set("insert", "1.0")
        else:
            w.select_range(0, "end")
            w.icursor("end")
    except Exception:
        pass
    return "break"


_HANDLERS = {
    KEY_V: _do_paste,
    KEY_C: _do_copy,
    KEY_X: _do_cut,
    KEY_A: _do_select_all,
}


def _on_control_key(event):
    """Обрабатывает Ctrl+V/C/X/A по коду клавиши — независимо от раскладки."""
    # Ctrl+Shift+... и Alt не перехватываем
    if event.state & 0x20000:          # Alt
        return None
    handler = _HANDLERS.get(getattr(event, "keycode", None))
    if handler is None:
        return None
    return handler(event)


def _on_copy_tree(event):
    """Ctrl+C в таблице — копирует значения выделенных строк."""
    tree = event.widget
    try:
        sel = tree.selection()
        if not sel:
            return "break"
        lines = []
        for iid in sel:
            vals = tree.item(iid, "values")
            lines.append("\t".join(str(v) for v in vals))
        tree.clipboard_clear()
        tree.clipboard_append("\n".join(lines))
    except Exception:
        pass
    return "break"


def enable_clipboard_shortcuts(root) -> None:
    """Включает Ctrl+V/C/X/A во всех полях ввода независимо от раскладки.

    Вызывается один раз при старте: привязка идёт на класс виджета,
    поэтому работает и для полей, созданных позже.
    """
    try:
        for cls in _TEXT_CLASSES:
            root.bind_class(cls, "<Control-KeyPress>", _on_control_key, add="+")
        for cls in _TREE_CLASSES:
            root.bind_class(cls, "<Control-KeyPress>", _on_control_key, add="+")
            root.bind_class(cls, "<Control-c>", _on_copy_tree, add="+")
        logger.info("clipboard_fix: горячие клавиши буфера включены")
    except Exception as exc:                      # pragma: no cover
        logger.warning("clipboard_fix: не удалось включить привязки: %s", exc)


def attach_context_menu(widget) -> None:
    """Контекстное меню «Вырезать / Копировать / Вставить» для поля ввода.

    Полезно там, где пользователь работает мышью.
    """
    import tkinter as tk

    menu = tk.Menu(widget, tearoff=0)

    def _fire(fn):
        class _E:
            pass
        e = _E()
        e.widget = widget
        e.state = 0
        return lambda: fn(e)

    menu.add_command(label=t("ctx_cut"),  command=_fire(_do_cut))
    menu.add_command(label=t("ctx_copy"), command=_fire(_do_copy))
    menu.add_command(label=t("ctx_paste"),   command=_fire(_do_paste))
    menu.add_separator()
    menu.add_command(label=t("ctx_select_all"), command=_fire(_do_select_all))

    def _popup(event):
        try:
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    widget.bind("<Button-3>", _popup, add="+")
