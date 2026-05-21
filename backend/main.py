from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.daily_tick import run_tick
from app.core.fingerprint import load_templates

app = FastAPI(
    title="Attendance & Sales System",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    # Seed default admin account
    _seed()
    # Run daily tick (handles catch-up if app was offline)
    run_tick()
    # Load fingerprint templates into memory
    load_templates()


def _seed():
    from app.core.firestore_client import accounts
    from app.core.security import hash_password
    ref = accounts().document("admin")
    if not ref.get().exists:
        ref.set({
            "account_name": "admin",
            "account_type": "admin",
            "hashed_password": hash_password("admin123"),
        })


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "2.0.0"}
