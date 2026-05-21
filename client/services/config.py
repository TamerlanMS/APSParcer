import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".aps_parser" / "config.json"


class AppConfig:
    def __init__(self):
        self.server_url = "http://localhost:8000"
        self.api_key    = ""
        self.language   = "ru"
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.server_url = d.get("server_url", self.server_url)
                self.api_key    = d.get("api_key",    self.api_key)
                self.language   = d.get("language",   self.language)
            except Exception:
                pass

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({
            "server_url": self.server_url,
            "api_key":    self.api_key,
            "language":   self.language,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.server_url)
