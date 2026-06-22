import asyncio
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import pdf, database, auth
from app.api import users as users_api
from app.api import excel_template as excel_template_api
from app.api import corrections as corrections_api
from app.core.config import settings
from app.core.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Lifespan: background product embedding on startup ─────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run pre-embedding of products in background after startup."""
    # ── Auto-create any missing tables (safe: CREATE TABLE IF NOT EXISTS) ──────
    try:
        from app.core.database import engine
        from app.models.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("DB schema check complete (all tables present)")
    except Exception as exc:
        logger.error("DB schema check failed: %s", exc)

    if settings.OPENAI_API_KEY and settings.PINECONE_API_KEY and settings.PINECONE_HOST:
        async def _embed_task():
            # Small delay so the server is fully up before heavy work starts
            await asyncio.sleep(5)
            try:
                from app.services.embedder import embed_products_batch
                n = await embed_products_batch(AsyncSessionLocal)
                if n:
                    logger.info("Startup embedding complete: %d products upserted to Pinecone", n)
                else:
                    logger.info("Startup embedding: guard conditions not met (not Monday or no recent import)")
            except Exception as exc:
                logger.error("Startup embedding failed: %s", exc)

        asyncio.create_task(_embed_task())
    else:
        logger.info("OPENAI_API_KEY or PINECONE_API_KEY not set — AI matching disabled")

    yield   # server runs here


app = FastAPI(
    title="GQ-Builder API",
    description="Сервис обработки PDF спецификаций и формирования КП",
    version="2.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    lifespan=lifespan,
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
app.include_router(excel_template_api.router, prefix="/api/v1",  tags=["excel-template"])
app.include_router(corrections_api.router, prefix="/api/v1/corrections", tags=["corrections"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Global error handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
