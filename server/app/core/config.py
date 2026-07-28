from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://aps_user:aps_password@postgres:5432/aps_db"

    # JWT
    JWT_SECRET_KEY: str = secrets.token_hex(32)
    JWT_ALGORITHM: str  = "HS256"
    JWT_EXPIRE_HOURS: int = 12      # Время жизни токена (часов)

    # Legacy admin password for DB import (bcrypt hash, backward compat)
    ADMIN_PASSWORD_HASH: str = "$2b$12$placeholder_replace_in_env"

    # Superadmin seed — создаётся при первом запуске если нет пользователей
    SUPERADMIN_USERNAME: str = "admin"
    SUPERADMIN_PASSWORD: str = "change_me_on_first_login"

    # OpenAI — Phase 2 AI matching
    OPENAI_API_KEY: str = ""
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"   # 1536 dims
    OPENAI_CHAT_MODEL:  str = "gpt-4o-mini"              # reranking
    AI_CONFIDENCE_THRESHOLD: float = 0.72  # cosine similarity floor

    # Embedding budget guard — stops vectorization before exceeding this daily limit.
    # text-embedding-3-small = $0.020 / 1M tokens
    # text-embedding-3-large = $0.130 / 1M tokens
    # text-embedding-ada-002 = $0.100 / 1M tokens
    EMBED_DAILY_BUDGET_USD: float = 1.60

    # Pinecone — vector index (Phase 2)
    # PINECONE_API_KEY  — API key from console.pinecone.io
    # PINECONE_HOST     — index host URL, e.g. https://<index>-<project>.svc.<env>.pinecone.io
    PINECONE_API_KEY: str = ""
    PINECONE_HOST:    str = ""

    # Analog search provider keys
    # DKC  — master_key из личного кабинета api.dkc.ru
    DKC_API_KEY: str = ""
    # EKF IMS3 B2B портал (ims3.ekf.su) — логин/пароль от аккаунта
    EKF_USERNAME: str = ""
    EKF_PASSWORD: str = ""
    # EKF  — cookie-строка сессии (альтернатива логин/пароль):
    #         войдите в браузере → DevTools → Application → Cookies → ims3.ekf.su
    #         скопируйте всю строку → EKF_COOKIE=token=xxx; session=yyy; ...
    EKF_COOKIE:   str = ""
    # EKF  — Bearer-токен публичного Partner API (опционально, ekfgroup.com/ru/support/api)
    EKF_API_KEY:  str = ""
    # IEK  — cookie-строка сессии asist.iek.ru (скопировать из браузера
    #         после входа: DevTools → Application → Cookies → asist.iek.ru)
    IEK_COOKIE:  str = ""

    DEBUG: bool = False

    # Valid API keys for desktop client (backward compat)
    API_KEYS: List[str] = [
        "APS-K1-X7mN2pQrL9vW4bYcJ6sT8uE3fH5kZ",
        "APS-K2-R4nD8wA1mK7vP3xB9yU6tF2hG5jQ0",
        "APS-K3-V9cL5eN2rM8wT4zK1pX7yB3sF6dH0",
        "APS-K4-Q2jH8mR5tW7nL4cX1bY9vP6kD3sE0",
        "APS-K5-B6wF1pK9eL3rN8mH5xQ2yV7tJ4cU0",
        "APS-K6-T3sY7vM2kB8nR5wL1eH9xP4jQ6fD0",
        "APS-K7-N5eP2bL8wK4rH7mQ1xT9yJ3vF6cS0",
        "APS-K8-H8kQ3mN6tB1rL9eW5xV2yP4jD7sF0",
        "APS-K9-L1xB7eW4mK2rN9pH6tQ8yV3jF5cD0",
        "APS-K10-P4yN9vL7bK3wH2mR8xQ5eT1jF6sD0",
    ]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
