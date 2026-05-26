import time
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import pdf, database, auth
from app.api import users as users_api
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="APS Parser API",
    description="Сервис обработки PDF спецификаций АПС",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging middleware ────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирует каждый запрос с временем выполнения и пользователем (если JWT)."""
    start = time.perf_counter()

    # Пытаемся извлечь имя пользователя из JWT без полной валидации
    user_info = "-"
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from app.core.security import decode_token
            payload = decode_token(auth_header.removeprefix("Bearer ").strip())
            user_info = f"{payload.get('username', '?')}[{payload.get('role', '?')}]"
        except Exception:
            user_info = "invalid_token"

    response = await call_next(request)

    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} "
        f"→ {response.status_code} "
        f"({elapsed:.1f}ms) "
        f"user={user_info} "
        f"ip={request.client.host if request.client else '-'}"
    )
    return response


# ── Routers ───────────────────────────────────────────────────────────────────

# Legacy API-key auth (backward compat with old desktop client)
app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["auth"])
# JWT auth + user management (Phase 1)
app.include_router(users_api.router)                           # has prefix="/api/v1" internally
app.include_router(pdf.router,      prefix="/api/v1/pdf",      tags=["pdf"])
app.include_router(database.router, prefix="/api/v1/database", tags=["database"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Global error handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
