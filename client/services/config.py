import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".aps_parser" / "config.json"


class AppConfig:
    def __init__(self):
        # Persisted settings
        self.server_url    = "http://localhost:8000"
        self.api_key       = ""
        self.language      = "ru"
        self.last_username = ""   # last successfully logged-in username

        # Session-only (JWT) — never written to disk
        self.jwt_token:      str = ""
        self.user_id:        int = 0
        self.user_username:  str = ""
        self.user_full_name: str = ""
        self.user_role:      str = ""
        self.user_segment:   str = "ss"   # ss / os / sil

        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.server_url    = d.get("server_url",    self.server_url)
                self.api_key       = d.get("api_key",       self.api_key)
                self.language      = d.get("language",      self.language)
                self.last_username = d.get("last_username", self.last_username)
            except Exception:
                pass

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({
            "server_url":    self.server_url,
            "api_key":       self.api_key,
            "language":      self.language,
            "last_username": self.last_username,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_user(self, data: dict):
        """Заполняет поля из ответа POST /auth/login."""
        self.jwt_token      = data.get("access_token", "")
        self.user_id        = data.get("user_id", 0)
        self.user_username  = data.get("username", "")
        self.user_full_name = data.get("full_name", "")
        self.user_role      = data.get("role", "")
        self.user_segment   = data.get("segment", "ss") or "ss"

    def clear_user(self):
        """Сбрасывает JWT-сессию (logout)."""
        self.jwt_token      = ""
        self.user_id        = 0
        self.user_username  = ""
        self.user_full_name = ""
        self.user_role      = ""
        self.user_segment   = "ss"

    @property
    def is_admin(self) -> bool:
        return self.user_role in ("superadmin", "administrator")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.server_url)

    @property
    def is_logged_in(self) -> bool:
        return bool(self.jwt_token)
