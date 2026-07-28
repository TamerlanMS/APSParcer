"""
Провайдеры поиска аналогов.

DKC    — api.dkc.ru (нужен DKC_API_KEY)
EKF    — ims3.ekf.su B2B портал → Hasura GraphQL (EKF_USERNAME + EKF_PASSWORD)
IEK    — asist.iek.ru (IEK_COOKIE)
CHINT  — kupichint.ru
BonPet — bonpet.tech
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

ProviderResult = Tuple[List["AnalogResult"], Optional[str]]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*;q=0.9",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

HASURA_URL = "https://hasura.ekfgroup.com/v1/graphql"

EKF_GQL_MUTATION = """
mutation MasterCostGetAnalogs(
  $rows: [Ims3MasterCostGetAnalogsRowsInput!]!,
  $is_like_search: Boolean
) {
  analogs: ims3_mastercost_get_analogs(
    rows: $rows
    is_like_search: $is_like_search
  ) {
    analog
    name
    short_name
    price
    quantity
    vendor_code
    brand
    analogs {
      id
      parent_id
      name
      short_name
      price
      quantity
      multiplicity
      vendor_code
      __typename
    }
    __typename
  }
}
""".strip()


@dataclass
class AnalogResult:
    analog_article: str
    analog_name: Optional[str] = None
    source: str = ""


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=BROWSER_HEADERS, follow_redirects=True, timeout=20)


def _is_json(r: httpx.Response) -> bool:
    return "json" in r.headers.get("content-type", "")


def _dbg(label: str, r: httpx.Response) -> None:
    ct = r.headers.get("content-type", "?")
    log.info("ANALOG_DBG [%s] status=%s ct=%s body=%s",
             label, r.status_code, ct, r.text[:800].replace("\n", " "))


def _extract_items(data, orig: str, source: str) -> List[AnalogResult]:
    results: List[AnalogResult] = []
    seen: set = set()

    def _add(art, name=None):
        art = str(art).strip()
        if art and art.upper() != orig.upper() and art not in seen:
            seen.add(art)
            results.append(AnalogResult(
                analog_article=art,
                analog_name=str(name)[:120] if name else None,
                source=source,
            ))

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                art = (item.get("article") or item.get("code")
                       or item.get("vendor_code") or item.get("sku"))
                name = item.get("name") or item.get("title") or item.get("short_name")
                if art:
                    _add(art, name)
            elif isinstance(item, str):
                _add(item)
    elif isinstance(data, dict):
        for key in ("analogs", "items", "products", "data", "result",
                    "results", "list", "analogues"):
            val = data.get(key)
            if val:
                sub = _extract_items(val, orig, source)
                if sub:
                    return sub
        for val in data.values():
            if isinstance(val, (list, dict)):
                sub = _extract_items(val, orig, source)
                if sub:
                    return sub
    return results


# ─────────────────────────────── DKC ─────────────────────────────────────────

_dkc_token: Optional[str] = None
_dkc_token_expires: Optional[datetime] = None


async def _dkc_get_token(client: httpx.AsyncClient) -> Optional[str]:
    global _dkc_token, _dkc_token_expires
    if _dkc_token and _dkc_token_expires and datetime.utcnow() < _dkc_token_expires:
        return _dkc_token
    key = getattr(settings, "DKC_API_KEY", "")
    if not key:
        return None
    try:
        r = await client.get(
            f"https://api.dkc.ru/v1/auth.access.token/{key}", timeout=10)
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token") or data.get("AccessToken")
        if token:
            _dkc_token = token
            _dkc_token_expires = datetime.utcnow() + timedelta(hours=23)
            return token
    except Exception as e:
        log.warning("DKC auth failed: %s", e)
    return None


async def search_dkc(article: str) -> ProviderResult:
    key = getattr(settings, "DKC_API_KEY", "")
    if not key:
        return [], (
            "DKC_API_KEY не настроен.\n"
            "Получите master_key в личном кабинете api.dkc.ru\n"
            "и добавьте в .env: DKC_API_KEY=ваш_ключ"
        )
    async with _make_client() as client:
        token = await _dkc_get_token(client)
        if not token:
            return [], "DKC: не удалось получить AccessToken. Проверьте DKC_API_KEY."
        try:
            r = await client.get(
                "https://api.dkc.ru/v1/catalog/material/analogs",
                params={"code": article},
                headers={**BROWSER_HEADERS, "AccessToken": token},
                timeout=15,
            )
            _dbg("dkc/analogs", r)
            r.raise_for_status()
            results = _extract_items(r.json(), article, "dkc")
            return results, (None if results else f"DKC: аналог для «{article}» не найден")
        except httpx.HTTPStatusError as e:
            return [], f"DKC API: HTTP {e.response.status_code}"
        except Exception as e:
            return [], f"DKC: {e}"


# ─────────────────────────────── EKF IMS3 → Hasura GraphQL ───────────────────
#
# Схема работы:
#   1. POST https://ims3.ekf.su/api/auth/login → JWT
#      JWT хранится как cookie "apollo-token" (@nuxtjs/apollo)
#   2. POST https://hasura.ekfgroup.com/v1/graphql
#      Authorization: Bearer <JWT>
#      mutation MasterCostGetAnalogs(rows:[{search:article}], is_like_search:true)
#   3. Парсим data.analogs[].analogs[].vendor_code → артикулы EKF

EKF_LOGIN_MUTATION = """
mutation login($username: String!, $password: String!) {
  login: ims3_login(login: $username, password: $password) {
    access_token
    __typename
  }
}
""".strip()

_ekf_jwt: Optional[str] = None
_ekf_jwt_expires: Optional[datetime] = None
_ekf_last_error: Optional[str] = None   # последняя ошибка — для диагностики


async def _ekf_login(client: httpx.AsyncClient) -> Tuple[Optional[str], Optional[str]]:
    """Авторизация через Hasura GraphQL mutation ims3_login.
    Возвращает (access_token, error_message). При успехе error=None."""
    global _ekf_jwt, _ekf_jwt_expires, _ekf_last_error

    # Проверяем кэш
    if _ekf_jwt and _ekf_jwt_expires and datetime.utcnow() < _ekf_jwt_expires:
        return _ekf_jwt, None

    username = getattr(settings, "EKF_USERNAME", "")
    password = getattr(settings, "EKF_PASSWORD", "")
    if not username or not password:
        return None, "EKF: логин/пароль не заданы в настройках сервера"

    try:
        r = await client.post(
            HASURA_URL,
            json={
                "operationName": "login",
                "variables": {"username": username, "password": password},
                "query": EKF_LOGIN_MUTATION,
            },
            headers={
                **BROWSER_HEADERS,
                "Content-Type": "application/json",
                "Origin":  "https://ims3.ekf.su",
                "Referer": "https://ims3.ekf.su/login",
            },
            timeout=15,
        )
        _dbg("ekf_gql_login", r)

        if r.status_code == 200 and _is_json(r):
            data = r.json()
            token = (
                (data.get("data") or {}).get("login", {}).get("access_token")
                or (data.get("data") or {}).get("access_token")
            )
            if token:
                _ekf_jwt = token
                _ekf_jwt_expires = datetime.utcnow() + timedelta(days=6)
                _ekf_last_error = None
                log.info("EKF IMS3: авторизация успешна (GraphQL)")
                return token, None
            # GQL-ошибка внутри 200 (неверный логин/пароль)
            gql_errors = data.get("errors") or []
            msg = gql_errors[0].get("message", "неверный ответ") if gql_errors else "токен не найден"
            err = f"EKF: ошибка авторизации — {msg}"
            log.warning("EKF IMS3: %s | ответ: %s", msg, str(data)[:200])
        elif r.status_code in (403, 429):
            err = (f"EKF: сервер вернул HTTP {r.status_code} — "
                   "возможно, API блокирует запросы с серверного IP. "
                   "Добавьте EKF_COOKIE из браузера в .env как запасной метод.")
            log.warning("EKF IMS3: login blocked HTTP %s", r.status_code)
        else:
            err = f"EKF: HTTP {r.status_code} при авторизации"
            log.warning("EKF IMS3: login HTTP %s — %s", r.status_code, r.text[:200])

    except httpx.ConnectError as e:
        err = f"EKF: нет связи с {HASURA_URL} — {e}"
        log.error("EKF IMS3: connect error: %s", e)
    except httpx.TimeoutException:
        err = "EKF: таймаут подключения к hasura.ekfgroup.com (>15 с)"
        log.error("EKF IMS3: login timeout")
    except Exception as e:
        err = f"EKF: неожиданная ошибка при авторизации — {e}"
        log.error("EKF IMS3 login error: %s", e)

    _ekf_last_error = err
    return None, err


def _parse_ekf_analogs(data: dict, orig: str) -> List[AnalogResult]:
    """
    Структура ответа MasterCostGetAnalogs:
    {
      "data": {
        "analogs": [          ← список результатов по каждой строке поиска
          {
            "vendor_code": "188020",   ← искомый артикул
            "name": "...",             ← наименование найденного товара
            "analogs": [               ← EKF-аналоги
              {"vendor_code": "mcb4763-4-32C-pro", "name": "...", ...},
              ...
            ]
          }
        ]
      }
    }
    """
    results: List[AnalogResult] = []
    seen: set = set()

    rows = (data.get("data") or {}).get("analogs") or []
    for row in rows:
        nested = row.get("analogs") or []
        for item in nested:
            art  = (item.get("vendor_code") or "").strip()
            name = (item.get("name") or item.get("short_name") or "").strip()
            if art and art.upper() != orig.upper() and art not in seen:
                seen.add(art)
                results.append(AnalogResult(
                    analog_article=art,
                    analog_name=name[:120] if name else None,
                    source="ekf",
                ))

    return results


async def search_ekf(article: str) -> ProviderResult:
    ekf_user   = getattr(settings, "EKF_USERNAME", "")
    ekf_pass   = getattr(settings, "EKF_PASSWORD", "")
    ekf_cookie = getattr(settings, "EKF_COOKIE",  "")
    ekf_key    = getattr(settings, "EKF_API_KEY", "")

    if not ekf_user and not ekf_cookie and not ekf_key:
        return [], (
            "EKF: не настроены учётные данные.\n"
            "Добавьте в .env:\n"
            "EKF_USERNAME=ваш_логин\n"
            "EKF_PASSWORD=ваш_пароль\n"
            "(от аккаунта на ims3.ekf.su)"
        )

    login_error: Optional[str] = None

    async with _make_client() as client:

        # ── 1. Логин/пароль → JWT → Hasura GraphQL ──────────────────────────
        if ekf_user and ekf_pass:
            jwt, login_error = await _ekf_login(client)
            if jwt:
                r = await _call_hasura(client, jwt, article)
                if r is not None:
                    _dbg("ekf_hasura", r)
                    if r.status_code == 200 and _is_json(r):
                        results = _parse_ekf_analogs(r.json(), article)
                        if results:
                            return results, None
                        return [], f"EKF: аналог для «{article}» не найден"
                    elif r.status_code == 401:
                        # JWT протух — сбрасываем и повторяем
                        global _ekf_jwt, _ekf_jwt_expires
                        _ekf_jwt = None
                        _ekf_jwt_expires = None
                        jwt2, _ = await _ekf_login(client)
                        if jwt2:
                            r2 = await _call_hasura(client, jwt2, article)
                            if r2 and r2.status_code == 200 and _is_json(r2):
                                results = _parse_ekf_analogs(r2.json(), article)
                                return results, (None if results
                                                 else f"EKF: аналог для «{article}» не найден")
                    elif r.status_code in (403, 429):
                        login_error = (
                            f"EKF: Hasura вернул HTTP {r.status_code} — "
                            "API может блокировать серверные IP-адреса. "
                            "Попробуйте добавить EKF_COOKIE из браузера в .env."
                        )
                    else:
                        login_error = f"EKF: Hasura HTTP {r.status_code}"
                else:
                    # r is None — сетевая ошибка уже залогирована в _call_hasura
                    if not login_error:
                        login_error = "EKF: нет ответа от hasura.ekfgroup.com (сетевая ошибка)"

        # ── 2. Ручной apollo-token cookie (запасной) ─────────────────────────
        if ekf_cookie:
            r = await _call_hasura(client, ekf_cookie, article)
            if r and r.status_code == 200 and _is_json(r):
                results = _parse_ekf_analogs(r.json(), article)
                if results:
                    return results, None

        # ── 3. Partner API (EKF_API_KEY) ─────────────────────────────────────
        if ekf_key:
            auth_hdrs = {**BROWSER_HEADERS, "Authorization": f"Bearer {ekf_key}"}
            for ver in ("v2", "v1", "v3"):
                url = f"https://ekfgroup.com/api/{ver}/EKF/catalog/product-analogs"
                try:
                    r = await client.get(url, params={"article": article},
                                          headers=auth_hdrs, timeout=15)
                    _dbg(f"ekf_partner/{ver}", r)
                    if r.status_code == 200 and _is_json(r):
                        results = _extract_items(r.json(), article, "ekf")
                        if results:
                            return results, None
                    elif r.status_code == 401:
                        break
                except Exception:
                    pass

    # Если всё упало — возвращаем реальную причину, а не просто "не найден"
    return [], login_error or f"EKF: аналог для «{article}» не найден"


async def _call_hasura(
    client: httpx.AsyncClient, jwt: str, article: str
) -> Optional[httpx.Response]:
    """POST запрос к Hasura GraphQL с JWT."""
    try:
        return await client.post(
            HASURA_URL,
            json={
                "operationName": "MasterCostGetAnalogs",
                "variables": {
                    "rows": [{"search": article}],
                    "is_like_search": True,
                },
                "query": EKF_GQL_MUTATION,
            },
            headers={
                **BROWSER_HEADERS,
                "Authorization":  f"Bearer {jwt}",
                "Content-Type":   "application/json",
                "Origin":         "https://ims3.ekf.su",
                "Referer":        "https://ims3.ekf.su/",
            },
            timeout=20,
        )
    except Exception as e:
        log.error("EKF Hasura request failed: %s", e)
        return None


# ─────────────────────────────── IEK ASIST ───────────────────────────────────

async def search_iek(article: str) -> ProviderResult:
    iek_cookie = getattr(settings, "IEK_COOKIE", "")

    async with _make_client() as client:
        if iek_cookie:
            hdrs = {**BROWSER_HEADERS,
                    "Cookie":  iek_cookie,
                    "Referer": "https://asist.iek.ru/"}
            for url, params in [
                ("https://asist.iek.ru/api/search",    {"q": article}),
                ("https://asist.iek.ru/api/search",    {"query": article}),
                ("https://asist.iek.ru/api/analogs",   {"q": article}),
                ("https://asist.iek.ru/api/v1/search", {"q": article}),
                ("https://asist.iek.ru/api/products",  {"search": article}),
            ]:
                try:
                    r = await client.get(url, params=params, headers=hdrs, timeout=15)
                    _dbg(f"iek/{url.split('/')[-1]}", r)
                    if r.status_code == 200 and _is_json(r):
                        results = _extract_items(r.json(), article, "iek")
                        if results:
                            return results, None
                    elif r.status_code in (401, 403):
                        break
                except Exception as e:
                    log.debug("IEK %s: %s", url, e)

        if not iek_cookie:
            return [], (
                "IEK: не настроен IEK_COOKIE.\n"
                "1. Войдите в asist.iek.ru в браузере\n"
                "2. DevTools → Application → Cookies\n"
                "3. .env: IEK_COOKIE=..."
            )
        return [], f"IEK ASIST: аналог для «{article}» не найден"


# ─────────────────────────────── CHINT ───────────────────────────────────────

async def search_chint(article: str) -> ProviderResult:
    async with _make_client() as client:
        for method, url, kw in [
            ("get",  f"https://kupichint.ru/api/analog?q={article}",       {}),
            ("get",  f"https://kupichint.ru/api/analog?article={article}", {}),
            ("post", "https://kupichint.ru/api/analog",
             {"json": {"q": article, "article": article}}),
        ]:
            try:
                r = await getattr(client, method)(url, **kw)
                if r.status_code == 200 and _is_json(r):
                    results = _extract_items(r.json(), article, "chint")
                    if results:
                        return results, None
            except Exception:
                pass
        return [], f"CHINT: аналог для «{article}» не найден"


# ─────────────────────────────── BonPet ──────────────────────────────────────

async def search_bonpet(article: str) -> ProviderResult:
    async with _make_client() as client:
        for method, url, kw in [
            ("get",  f"https://bonpet.tech/api/analog?article={article}", {}),
            ("get",  f"https://bonpet.tech/api/analogs?q={article}",      {}),
            ("post", "https://bonpet.tech/api/analog", {"json": {"article": article}}),
        ]:
            try:
                r = await getattr(client, method)(url, **kw)
                if r.status_code == 200 and _is_json(r):
                    results = _extract_items(r.json(), article, "bonpet")
                    if results:
                        return results, None
            except Exception:
                pass
        return [], "BonPet: сервис недоступен или аналог не найден"


# ─────────────────────────────── Registry ────────────────────────────────────

PROVIDERS: dict = {
    "dkc":    ("ДКС",    search_dkc),
    "ekf":    ("EKF",    search_ekf),
    "iek":    ("IEK",    search_iek),
    "chint":  ("CHINT",  search_chint),
    "bonpet": ("BonPet", search_bonpet),
}
