import requests
from typing import Tuple, Callable, Optional
from services.config import AppConfig


class ApiService:
    def __init__(self, config: AppConfig):
        self.config = config

    @property
    def _h(self) -> dict:
        return {"X-API-Key": self.config.api_key}

    @property
    def _base(self) -> str:
        return self.config.server_url.rstrip("/")

    def validate_key(self) -> Tuple[bool, str]:
        try:
            r = requests.post(
                f"{self._base}/api/v1/auth/validate",
                headers=self._h,
                timeout=10
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
                timeout=180
            )
        if progress_cb:
            progress_cb(90, "processing")
        r.raise_for_status()
        return r.json()

    def get_constants(self) -> dict:
        r = requests.get(
            f"{self._base}/api/v1/database/constants",
            headers=self._h,
            timeout=15
        )
        r.raise_for_status()
        return r.json()

    def get_products_count(self) -> int:
        r = requests.get(
            f"{self._base}/api/v1/database/products/count",
            headers=self._h,
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("count", 0)

    def import_products(self, file_path: str, password: str) -> dict:
        with open(file_path, "rb") as f:
            fname = file_path.replace("\\", "/").split("/")[-1]
            if fname.lower().endswith(".xlsm"):
                mime = "application/vnd.ms-excel.sheet.macroEnabled.12"
            else:
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
            if fname.lower().endswith(".xlsm"):
                mime = "application/vnd.ms-excel.sheet.macroEnabled.12"
            else:
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
            timeout=10
        )
        r.raise_for_status()
        return r.json()

    def get_all_products(self) -> list:
        """Возвращает все активные товары из БД (без пагинации) для заполнения листа БД в Excel."""
        r = requests.get(
            f"{self._base}/api/v1/database/products/all",
            headers=self._h,
            timeout=120
        )
        r.raise_for_status()
        return r.json()
