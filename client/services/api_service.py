import json
import os
import requests
from typing import Tuple, Callable, Optional
from services.config import AppConfig


class ApiService:
    def __init__(self, config: AppConfig):
        self.config = config

    @property
    def _h(self) -> dict:
        headers = {"X-API-Key": self.config.api_key}
        if self.config.jwt_token:
            headers["Authorization"] = f"Bearer {self.config.jwt_token}"
        return headers

    @property
    def _base(self) -> str:
        return self.config.server_url.rstrip("/")

    # ── Connection / auth ─────────────────────────────────────────────────────

    def validate_key(self) -> Tuple[bool, str]:
        try:
            r = requests.post(
                f"{self._base}/api/v1/auth/validate",
                headers={"X-API-Key": self.config.api_key},
                timeout=10,
            )
            if r.status_code == 200:
                return True, "ok"
            if r.status_code == 403:
                return False, "invalid_key"
            return False, f"server_error_{r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "no_connection"
        except Exception as e:
            return False, str(e)

    def get_users_list(self) -> list:
        try:
            r = requests.get(
                f"{self._base}/api/v1/auth/users-list",
                headers={"X-API-Key": self.config.api_key},
                timeout=8,
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def login(self, username: str, password: str) -> Tuple[bool, str, dict]:
        try:
            r = requests.post(
                f"{self._base}/api/v1/auth/login",
                json={"username": username, "password": password},
                headers={"X-API-Key": self.config.api_key},
                timeout=10,
            )
            if r.status_code == 200:
                return True, "", r.json()
            if r.status_code == 401:
                return False, "wrong_creds", {}
            return False, "error", {}
        except requests.exceptions.ConnectionError:
            return False, "no_connection", {}
        except Exception:
            return False, "error", {}

    def logout(self) -> None:
        if not self.config.jwt_token:
            return
        try:
            requests.post(
                f"{self._base}/api/v1/auth/logout",
                headers=self._h,
                timeout=5,
            )
        except Exception:
            pass
        finally:
            self.config.clear_user()

    # ── PDF ───────────────────────────────────────────────────────────────────

    def parse_pdf_stream(self, pdf_path: str,
                         progress_cb: Optional[Callable] = None,
                         ai_mode: bool = False) -> dict:
        """POST file to /pdf/parse-stream, read SSE progress events, return result.

        progress_cb(pct: int, stage: str, msg: str) is called for each event.
        Raises RuntimeError on server error or if stream closes without result.
        """
        fname = os.path.basename(pdf_path)
        if progress_cb:
            progress_cb(3, "upload", "Отправка файла на сервер...")

        with open(pdf_path, "rb") as f:
            files = {"file": (fname, f, "application/pdf")}
            with requests.post(
                f"{self._base}/api/v1/pdf/parse-stream",
                files=files,
                headers=self._h,
                params={"ai_mode": "true" if ai_mode else "false"},
                stream=True,
                timeout=3600,  # 1 hour — OCR of large scanned PDFs can take 20-40 min
            ) as r:
                r.raise_for_status()
                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue
                    if isinstance(raw_line, bytes):
                        raw_line = raw_line.decode("utf-8", errors="replace")
                    if not raw_line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(raw_line[6:])
                    except json.JSONDecodeError:
                        continue
                    if "error" in event:
                        raise RuntimeError(event["error"])
                    if "done" in event:
                        return event["result"]
                    if progress_cb and "pct" in event:
                        progress_cb(
                            int(event["pct"]),
                            event.get("stage", ""),
                            event.get("msg", ""),
                        )
        raise RuntimeError("Сервер закрыл соединение без результата")

    def parse_pdf(self, pdf_path: str,
                  progress_cb: Optional[Callable] = None,
                  ai_mode: bool = False) -> dict:
        """Legacy non-streaming parse (kept for compatibility)."""
        with open(pdf_path, "rb") as f:
            fname = pdf_path.replace("\\", "/").split("/")[-1]
            files = {"file": (fname, f, "application/pdf")}
            if progress_cb:
                progress_cb(15, "sending", "Отправка файла...")
            r = requests.post(
                f"{self._base}/api/v1/pdf/parse",
                files=files,
                headers=self._h,
                params={"ai_mode": "true" if ai_mode else "false"},
                timeout=900,
            )
        if progress_cb:
            progress_cb(90, "processing", "Обработка...")
        r.raise_for_status()
        return r.json()

    def rematch_ai(self, items: list) -> dict:
        """Send items to server AI re-matcher. Returns updated match results."""
        r = requests.post(
            f"{self._base}/api/v1/pdf/rematch",
            json={"items": items},
            headers=self._h,
            timeout=300,
        )
        r.raise_for_status()
        return r.json()

    def get_pdf_history(self, limit: int = 200) -> list:
        r = requests.get(
            f"{self._base}/api/v1/pdf/history",
            headers=self._h,
            params={"limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def download_base_template(self, save_path: str) -> bool:
        """Download pre-built .xlsm (БД + Const filled) from server.

        Returns True on success, False if not available (404 = no import yet).
        Raises on network/server errors.
        """
        r = requests.get(
            f"{self._base}/api/v1/database/base-template",
            headers=self._h,
            timeout=120,
            stream=True,
        )
        if r.status_code == 404:
            return False
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return True

    # ── Database ──────────────────────────────────────────────────────────────

    def get_constants(self) -> dict:
        r = requests.get(
            f"{self._base}/api/v1/database/constants",
            headers=self._h,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_products_count(self) -> int:
        r = requests.get(
            f"{self._base}/api/v1/database/products/count",
            headers=self._h,
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("count", 0)

    def import_products(self, file_path: str, password: str) -> dict:
        with open(file_path, "rb") as f:
            fname = file_path.replace("\\", "/").split("/")[-1]
            mime = (
                "application/vnd.ms-excel.sheet.macroEnabled.12"
                if fname.lower().endswith(".xlsm")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            files = {"file": (fname, f, mime)}
            r = requests.post(
                f"{self._base}/api/v1/database/import/products",
                files=files,
                headers=self._h,
                params={"password": password},
                timeout=180,
            )
        r.raise_for_status()
        return r.json()

    def import_constants(self, file_path: str, password: str) -> dict:
        with open(file_path, "rb") as f:
            fname = file_path.repla