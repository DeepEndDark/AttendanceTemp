from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run blocking startup tasks in a thread so the event loop
    # stays responsive for incoming requests during startup.
    await asyncio.to_thread(_startup)
    yield
    # Shutdown — nothing needed; fingerprint atexit handles reader cleanup


def _startup():
    from app.core.daily_tick import (
        run_tick, auto_timeout_stale_sessions,
        start_nightly_timeout_scheduler,
    )
    from app.core.fingerprint import load_templates
    _seed()
    run_tick()
    auto_timeout_stale_sessions()
    start_nightly_timeout_scheduler()
    load_templates()


def _seed():
    from app.core.firestore_client import accounts
    from app.core.security import hash_password
    ref = accounts().document("admin")
    if not ref.get().exists:
        ref.set({
            "account_name":    "admin",
            "account_type":    "admin",
            "hashed_password": hash_password("admin123"),
        })


app = FastAPI(
    title="Attendance & Sales System",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "2.0.0"}