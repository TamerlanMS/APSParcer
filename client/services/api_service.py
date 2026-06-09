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

    def parse_pdf(self, pdf_path: str,
                  progress_cb: Optional[Callable] = None) -> dict:
        with open(pdf_path, "rb") as f:
            fname = pdf_path.replace("\\", "/").split("/")[-1]
            files = {"file": (fname, f, "application/pdf")}
            if progress_cb:
                progress_cb(15, "sending")
            r = requests.post(
                f"{self._base}/api/v1/pdf/parse",
                files=files,
                headers=self._h,
                timeout=900,
            )
        if progress_cb:
            progress_cb(90, "processing")
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
            fname = file_path.replace("\\", "/").split("/")[-1]
            mime = (
                "application/vnd.ms-excel.sheet.macroEnabled.12"
                if fname.lower().endswith(".xlsm")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            files = {"file": (fname, f, mime)}
            r = requests.post(
                f"{self._base}/api/v1/database/import/constants",
                files=files,
                headers=self._h,
                params={"password": password},
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def get_logs(self) -> list:
        r = requests.get(
            f"{self._base}/api/v1/database/logs",
            headers=self._h,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def get_all_products(self) -> list:
        r = requests.get(
            f"{self._base}/api/v1/database/products/all",
            headers=self._h,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    # ── User management ───────────────────────────────────────────────────────

    def get_users(self) -> list:
        r = requests.get(f"{self._base}/api/v1/users/", headers=self._h, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_roles(self) -> list:
        r = requests.get(f"{self._base}/api/v1/users/roles", headers=self._h, timeout=10)
        r.raise_for_status()
        return r.json()

    def create_user(self, data: dict) -> dict:
        r = requests.post(f"{self._base}/api/v1/users/", json=data, headers=self._h, timeout=10)
        r.raise_for_status()
        return r.json()

    def update_user(self, user_id: int, data: dict) -> dict:
        r = requests.patch(f"{self._base}/api/v1/users/{user_id}", json=data, headers=self._h, timeout=10)
        r.raise_for_status()
        return r.json()

    def delete_user(self, user_id: int) -> None:
        r = requests.delete(f"{self._base}/api/v1/users/{user_id}", headers=self._h, timeout=10)
        r.raise_for_status()

