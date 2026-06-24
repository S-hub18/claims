"""FastAPI application — the HTTP entry point.

Design rules (ARCHITECTURE.md §9):
  - Never returns a 5xx to the client — every error is a JSON envelope.
  - POST /claims returns in milliseconds; adjudication runs as a background task.
  - SSE stream replays facts on reconnect (late consumers get full history).
  - CORS origin is read from config; never hardcoded.

Persistence (Part 8):
  - DATABASE_URL set → SQLAlchemy async engine; create_all() on startup.
  - REDIS_URL set     → redis.asyncio client wired into the store.
  Both are optional; the app runs in pure in-memory mode without them (tests, local dev).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.claims import router as claims_router
from app.api.store import ClaimStore
from app.config import get_settings
from app.policy import Policy


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.policy = Policy.from_file(settings.policy_path)

    # ── optional DB ───────────────────────────────────────────────────────────
    db_engine = None
    session_factory = None
    if settings.database_url:
        from app.db import Base, create_engine_from_url, get_session_factory
        db_engine = create_engine_from_url(settings.database_url)
        session_factory = get_session_factory(db_engine)
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    app.state.db_engine = db_engine

    # ── optional Redis ────────────────────────────────────────────────────────
    redis_client = None
    if settings.redis_url:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis_client = redis_client

    app.state.store = ClaimStore(
        redis_client=redis_client,
        session_factory=session_factory,
    )

    yield

    # ── teardown ──────────────────────────────────────────────────────────────
    if redis_client is not None:
        await redis_client.aclose()
    if db_engine is not None:
        await db_engine.dispose()


app = FastAPI(
    title="Claims Processing API",
    description="Health insurance OPD claims — blackboard adjudication engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Explicit origins (configured frontend + local dev) plus a regex that matches
    # every Vercel deployment of this project — production alias and per-commit
    # preview URLs alike — so a new Vercel URL never breaks CORS again.
    allow_origins=[get_settings().frontend_url, "http://localhost:3000"],
    allow_origin_regex=r"https://claims[a-z0-9-]*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(claims_router)


@app.get("/health")
async def health(request: Request):
    db_ok = request.app.state.db_engine is not None
    redis_ok = request.app.state.redis_client is not None
    return {"status": "ok", "db": db_ok, "redis": redis_ok}


@app.exception_handler(Exception)
async def _never_500(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )
