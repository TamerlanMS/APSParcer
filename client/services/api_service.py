import json
import os
import requests
from typing import Tuple, Callable, Optional
from services.config import AppConfig


class SessionExpiredError(PermissionError):
    """Raised when the server returns 403 Forbidden on an admin endpoint.
    Usually means the JWT token is expired or the user lost admin rights."""


class ApiService:
    def __init__(self, config: AppConfig):
        self.config = config

    def _raise_for_status(self, r) -> None:
        """Like r.raise_for_status() but converts 403 → SessionExpiredError."""
        if r.status_code == 403:
            raise SessionExpiredError(
                "Сессия истекла или недостаточно прав. Войдите в систему заново."
            )
        r.raise_for_status()

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

    # ── User management ──────────────────────────────────────────────────────

    def get_roles(self) -> list:
        """GET /users/roles — список всех ролей."""
        r = requests.get(
            f"{self._base}/api/v1/users/roles",
            headers=self._h, timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def get_users(self) -> list:
        """GET /users/ — список всех пользователей (superadmin)."""
        r = requests.get(
            f"{self._base}/api/v1/users/",
            headers=self._h, timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def create_user(self, data: dict) -> dict:
        """POST /users/ — создать пользователя."""
        r = requests.post(
            f"{self._base}/api/v1/users/",
            json=data, headers=self._h, timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def update_user(self, user_id: int, data: dict) -> dict:
        """PATCH /users/{id} — обновить пользователя."""
        r = requests.patch(
            f"{self._base}/api/v1/users/{user_id}",
            json=data, headers=self._h, timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def delete_user(self, user_id: int) -> None:
        """DELETE /users/{id} — деактивировать пользователя."""
        r = requests.delete(
            f"{self._base}/api/v1/users/{user_id}",
            headers=self._h, timeout=10,
        )
        r.raise_for_status()

    # ── PDF ───────────────────────────────────────────────────────────────────

    def parse_pdf_stream(self, pdf_path: str,
                         progress_cb: Optional[Callable] = None,
                         ai_mode: bool = False,
                         segments: Optional[list] = None) -> dict:
        """POST file to /pdf/parse-stream, read SSE progress events, return result.

        segments: list of segment codes to search, e.g. ["ss"] or ["ss","os","sil"].
        progress_cb(pct: int, stage: str, msg: str) is called for each event.
        Raises RuntimeError on server error or if stream closes without result.
        """
        fname = os.path.basename(pdf_path)
        if progress_cb:
            progress_cb(3, "upload", "Отправка файла на сервер...")

        seg_str = ",".join(segments) if segments else "ss"

        with open(pdf_path, "rb") as f:
            files = {"file": (fname, f, "application/pdf")}
            with requests.post(
                f"{self._base}/api/v1/pdf/parse-stream",
                files=files,
                headers=self._h,
                params={"ai_mode": "true" if ai_mode else "false", "segments": seg_str},
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

    def parse_pdf_multi_stream(
        self,
        pdf_paths: list,
        progress_cb=None,   # (file_idx, filename, pct, stage, msg)
        file_done_cb=None,  # (file_idx, filename, result)
        ai_mode: bool = False,
        segments=None,
    ) -> list:
        """POST multiple PDF files to /pdf/parse-multi-stream, return list of results.

        progress_cb(file_idx, filename, pct, stage, msg) — called per-file SSE progress event.
        file_done_cb(file_idx, filename, result)         — called when each file finishes.
        Returns list of result dicts (one per file that succeeded).
        """
        seg_str = ",".join(segments) if segments else "ss"
        open_files = []
        try:
            multi_files = []
            for path in pdf_paths:
                fname = os.path.basename(path)
                fobj = open(path, "rb")
                open_files.append(fobj)
                multi_files.append(("files", (fname, fobj, "application/pdf")))

            with requests.post(
                f"{self._base}/api/v1/pdf/parse-multi-stream",
                files=multi_files,
                headers=self._h,
                params={"ai_mode": "true" if ai_mode else "false", "segments": seg_str},
                stream=True,
                timeout=7200,
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

                    if "all_done" in event:
                        return event.get("results", [])

                    if "file_error" in event:
                        if progress_cb:
                            progress_cb(
                                event.get("file_idx", 0),
                                event.get("filename", ""),
                                100, "error", event["file_error"],
                            )
                        continue

                    if "file_done" in event:
                        if file_done_cb:
                            file_done_cb(
                                event.get("file_idx", 0),
                                event.get("filename", ""),
                                event.get("result", {}),
                            )
                        continue

                    if progress_cb and "pct" in event:
                        progress_cb(
                            event.get("file_idx", 0),
                            event.get("filename", ""),
                            int(event["pct"]),
                            event.get("stage", ""),
                            event.get("msg", ""),
                        )
        finally:
            for fobj in open_files:
                try:
                    fobj.close()
                except Exception:
                    pass
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

    # ── Excel Template ────────────────────────────────────────────────────────

    def get_excel_template_info(self) -> dict:
        """GET /admin/excel-template — возвращает мета-информацию об активном шаблоне."""
        r = requests.get(
            f"{self._base}/api/v1/admin/excel-template",
            headers=self._h,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def upload_excel_template(self, file_path: str, description: str = "") -> dict:
        """POST /admin/excel-template — загружает новый шаблон .xlsm на сервер."""
        with open(file_path, "rb") as fh:
            r = requests.post(
                f"{self._base}/api/v1/admin/excel-template",
                headers={k: v for k, v in self._h.items() if k.lower() != "content-type"},
                files={"file": (file_path.split("/")[-1].split("\\")[-1], fh,
                                "application/vnd.ms-excel.sheet.macroEnabled.12")},
                data={"description": description},
                timeout=60,
            )
        r.raise_for_status()
        return r.json()

    def download_excel_template(self, save_path: str) -> bool:
        """GET /admin/excel-template/download — скачивает текущий шаблон .xlsm."""
        r = requests.get(
            f"{self._base}/api/v1/admin/excel-template/download",
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

    def get_product_prices(self, articles: list) -> list:
        """Return price fields for the given product articles (diagnostic)."""
        r = requests.get(
            f"{self._base}/api/v1/database/products/prices",
            headers=self._h,
            params={"articles": ",".join(articles)},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("products", [])

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

    def import_products(self, file_path: str, password: str,
                        segment: str = "ss") -> dict:
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
                params={"password": password, "segment": segment},
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
                timeout=180,
            )
        r.raise_for_status()
        return r.json()

    def pinecone_status(self) -> dict:
        """GET /database/pinecone/status — статус Pinecone индекса."""
        r = requests.get(
            f"{self._base}/api/v1/database/pinecone/status",
            headers=self._h, timeout=15,
        )
        self._raise_for_status(r)
        return r.json()

    def pinecone_reconnect(self) -> dict:
        """POST /database/pinecone/reconnect — сбросить кеш и переподключиться."""
        r = requests.post(
            f"{self._base}/api/v1/database/pinecone/reconnect",
            headers=self._h, timeout=15,
        )
        self._raise_for_status(r)
        return r.json()

    def start_vectorization(self, segment: str = "all") -> dict:
        """Запускает ручную векторизацию товаров в Pinecone (только admin).

        Args:
            segment: "ss", "os", "sil" или "all" (по умолчанию — все сегменты).
        """
        params = {} if segment == "all" else {"segment": segment}
        r = requests.post(
            f"{self._base}/api/v1/database/vectorize",
            headers=self._h,
            params=params,
            timeout=15,
        )
        self._raise_for_status(r)
        return r.json()

    def get_embed_budget(self) -> dict:
        """GET /database/embed-budget — дневной бюджет векторизации."""
        r = requests.get(
            f"{self._base}/api/v1/database/embed-budget",
            headers=self._h,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def get_brand_stats(self) -> list:
        """GET /database/brands/stats — количество позиций по брендам (все сегменты)."""
        r = requests.get(
            f"{self._base}/api/v1/database/brands/stats",
            headers=self._h,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_db_stats(self) -> dict:
        """GET /database/stats — количество товаров по сегментам."""
        r = requests.get(
            f"{self._base}/api/v1/database/stats",
            headers=self._h,
            timeout=10,
        )
        self._raise_for_status(r)
        return r.json()

    def clear_segment(self, segment: str, hard: bool = False) -> dict:
        """DELETE /database/segment/{segment} — очистить сегмент БД."""
        import requests as _req
        r = _req.delete(
            f"{self._base}/api/v1/database/segment/{segment}",
            headers=self._h,
            params={"hard": str(hard).lower()},
            timeout=30,
        )
        self._raise_for_status(r)
        return r.json()

    def get_logs(self, limit: int = 50) -> list:
        """GET /database/logs — история импорта базы данных."""
        r = requests.get(
            f"{self._base}/api/v1/database/logs",
            headers=self._h,
            params={"limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ── Corrections (Phase 2.6 — ML learning from manager selections) ─────────

    def record_correction(
        self,
        original_name:       str,
        original_article:    str,
        original_status:     str,
        selected_product_id: int,
        session_id:          str = "",
    ) -> dict:
        """
        Записать исправление/подтверждение менеджера.
        Вызывается при выборе товара для красной строки или при ✓-подтверждении.
        Возвращает {"ok": True, "correction_id": ..., "product_id": ..., "indexed": ...}
        """
        try:
            r = requests.post(
                f"{self._base}/api/v1/corrections/record",
                json={
                    "original_name":       original_name,
                    "original_article":    original_article or "",
                    "original_status":     original_status or "",
                    "selected_product_id": selected_product_id,
                    "session_id":          session_id or "",
                },
                headers=self._h,
                timeout=20,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def search_products_by_text(self, query: str, article: str = "", top_k: int = 8) -> list:
        """
        Поиск товаров в БД по текстовому запросу (через Pinecone vector search).
        Используется в ArticleSearchDialog для красных строк.
        Возвращает список: [{"product_id", "article", "name", "similarity"}, ...]
        """
        try:
            r = requests.get(
                f"{self._base}/api/v1/corrections/search",
                params={"q": query, "article": article, "top_k": top_k},
                headers=self._h,
                timeout=15,
            )
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception:
            return []

    def search_products_by_article(self, article: str = "", name: str = "") -> list:
        """Legacy: поиск по отдельным полям. Используй search_products() для нового диалога."""
        return self.search_products(q=article or name, segment="")

    def search_products(
        self,
        q: str = "",
        segment: str = "",
        kaznisa_code: str = "",
        limit: int = 30,
    ) -> list:
        """
        Единый поиск товаров — ищет по артикулу, наименованию и коду КазНИИСА одновременно.

        Args:
            q:            поисковая строка (ищется во всех полях)
            segment:      "ss" / "os" / "sil" или "" (все сегменты)
            kaznisa_code: дополнительный фильтр по коду КазНИИСА
            limit:        максимум результатов
        """
        if not q and not kaznisa_code:
            return []
        params: dict = {"limit": limit}
        if q:
            params["q"] = q
        if segment:
            params["segment"] = segment
        if kaznisa_code:
            params["kaznisa_code"] = kaznisa_code
        try:
            r = requests.get(
                f"{self._base}/api/v1/database/products/search",
                params=params,
                headers=self._h,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("products", [])
        except Exception:
            pass
        return []

    # ── Фаза 4: Аналитика ────────────────────────────────────────────────────

    def get_analytics_summary(self, period: int = 30) -> dict:
        """GET /analytics/summary?period=N — сводная статистика системы."""
        r = requests.get(
            f"{self._base}/api/v1/analytics/summary",
            headers=self._h,
            params={"period": period},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_analytics_kpi(self, period: int = 30) -> dict:
        """GET /analytics/kpi?period=N — KPI по менеджерам."""
        r = requests.get(
            f"{self._base}/api/v1/analytics/kpi",
            headers=self._h,
            params={"period": period},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_analytics_brands(self, period: int = 30) -> dict:
        """GET /analytics/brands?period=N — топ брендов по числу ручных исправлений."""
        r = requests.get(
            f"{self._base}/api/v1/analytics/brands",
            headers=self._h,
            params={"period": period},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_analytics_ai_efficiency(self, period: int = 30) -> dict:
        """GET /analytics/ai-efficiency?period=N — эффективность ИИ-подбора."""
        r = requests.get(
            f"{self._base}/api/v1/analytics/ai-efficiency",
            headers=self._h,
            params={"period": period},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_price_history(self, article: str, segment: str = None) -> dict:
        """GET /analytics/price-history?article=xxx&segment=ss — история цен."""
        params = {"article": article}
        if segment:
            params["segment"] = segment
        r = requests.get(
            f"{self._base}/api/v1/analytics/price-history",
            headers=self._h,
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_analytics_anomalies(self, period: int = 30) -> dict:
        """GET /analytics/anomalies?period=N — аномалии цен за период."""
        r = requests.get(
            f"{self._base}/api/v1/analytics/anomalies",
            headers=self._h,
            params={"period": period},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_correction_stats(self) -> dict:
        """Статистика накопленных исправлений. {"total_corrections", "pinecone_indexed", "unique_products"}"""
        try:
            r = requests.get(
                f"{self._base}/api/v1/corrections/stats",
                headers=self._h,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            return {"total_corrections": 0, "pinecone_indexed": 0, "unique_products": 0}

    # ── Фаза 5: Подбор аналогов ────────────────────────────────────────────────────────

    def search_analogs(self, article: str, provider: str,
                        force_refresh: bool = False,
                        segment: str = "ss") -> dict:
        """
        POST /api/v1/analogs/search

        Возвращает:
            {
                "analogs": [
                    {
                        "analog_article": str,
                        "analog_name": str | None,
                        "source": str,
                        "db_match": dict | None,  # Product если найден в БД
                    }
                ],
                "cached": bool,
                "provider_error": str | None,
            }
        """
        r = requests.post(
            f"{self._base}/api/v1/analogs/search",
            headers=self._h,
            json={
                "article": article,
                "provider": provider,
                "force_refresh": force_refresh,
                "segment": segment,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_analog_diagnostics(self) -> dict:
        """GET /api/v1/analogs/diagnostics — проверяет настройки и связь с провайдерами."""
        r = requests.get(
            f"{self._base}/api/v1/analogs/diagnostics",
            headers=self._h,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
