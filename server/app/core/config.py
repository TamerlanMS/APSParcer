from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://aps_user:aps_password@postgres:5432/aps_db"

    # Security
    SECRET_KEY: str = secrets.token_hex(32)
    DEBUG: bool = False

    # Admin password for DB updates (hashed with bcrypt)
    ADMIN_PASSWORD_HASH: str = "$2b$12$placeholder_replace_in_env"

    # Valid API keys for desktop client (10 keys)
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
