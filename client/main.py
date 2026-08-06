import sys
import os

# Добавляем путь к корню клиента
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.config import AppConfig
from ui.main_window import MainApp
from ui.clipboard_fix import enable_clipboard_shortcuts


def main():
    config = AppConfig()
    app = MainApp(config)
    # Ctrl+V/C/X/A во всех полях ввода независимо от раскладки клавиатуры
    enable_clipboard_shortcuts(app)
    app.mainloop()


if __name__ == "__main__":
    main()
