from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

    # ── Firebase / Firestore init ─────────────────────────────
    # A missing credentials file must NOT crash the server.
    # The login page pings /health every 5 s; we must stay alive so the
    # frontend can display the login screen even when Firebase is not yet
    # configured.  All Firestore-dependent routes will raise 503 on their
    # own when they can't reach the DB.
    try:
        _seed()
    except FileNotFoundError as exc:
        log.error("\n" + "=" * 60)
        log.error("FIREBASE SETUP REQUIRED — backend started without database.")
        log.error(str(exc))
        log.error("The /health endpoint is still available.")
        log.error("=" * 60 + "\n")
        # Skip remaining startup tasks that need Firestore
        load_templates()   # fingerprint reader doesn't need Firebase
        return
    except Exception as exc:
        log.error("Firebase init failed (%s: %s) — continuing without DB.",
                  type(exc).__name__, exc)
        load_templates()
        return

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


@app.exception_handler(Exception)
async def firestore_connectivity_handler(request: Request, exc: Exception):
    """
    Distinguishes "Firestore/network is temporarily unreachable" from a real
    application bug, mid-session — not just at startup.

    _startup() in this file only handles missing credentials at boot time;
    it says nothing about Firestore having a transient outage once the
    backend is already serving live traffic (a real possibility for a
    cloud-hosted DB, separate from the local network dropping). Without
    this handler, any such failure bubbles up as a raw 500 with a Python
    traceback — which the frontend's _request() retry wrapper does NOT
    treat as retriable (it only retries on connection-level failures, not
    on a "successful" HTTP response that happens to carry a 500 body).

    Returning 503 here lets the frontend recognize this distinctly if it
    chooses to, and gives the person a clean message instead of a stack
    trace, without masking genuine application bugs (those still surface
    as 500 via FastAPI's default handling for exception types not listed
    below).
    """
    is_connectivity_issue = False

    try:
        from google.api_core import exceptions as gae
        if isinstance(exc, (gae.GoogleAPIError, gae.RetryError)):
            is_connectivity_issue = True
    except ImportError:
        pass

    if not is_connectivity_issue:
        try:
            import grpc
            if isinstance(exc, grpc.RpcError):
                is_connectivity_issue = True
        except ImportError:
            pass

    if not is_connectivity_issue:
        # Not a connectivity issue — let FastAPI's default handling apply
        # (re-raising here would lose the original traceback in some
        # ASGI server configurations, so log and return 500 explicitly).
        log.exception("Unhandled exception in %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {exc}"},
        )

    log.error(
        "Firestore/network connectivity error in %s: %s: %s",
        request.url.path, type(exc).__name__, exc,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database temporarily unreachable. Please try again "
                      "in a few seconds."
        },
    )


@app.get("/health", tags=["meta"])
def health():
    """
    Always returns 200 so the frontend network poller can confirm the
    backend process is alive regardless of Firebase state.
    The `firebase` field reports whether Firestore is reachable.
    """
    firebase_status = "unknown"
    try:
        from app.core.firestore_client import _get_db
        _get_db()
        firebase_status = "ok"
    except FileNotFoundError:
        firebase_status = "credentials_missing"
    except Exception:
        firebase_status = "error"
    return {"status": "ok", "version": "2.0.0", "firebase": firebase_status}