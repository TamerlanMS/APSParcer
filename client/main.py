import sys
import os

# Добавляем путь к корню клиента
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.config import AppConfig
from ui.main_window import MainApp


def main():
    config = AppConfig()
    app = MainApp(config)
    app.mainloop()


if __name__ == "__main__":
    main()
