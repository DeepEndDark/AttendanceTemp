"""
Firestore client — single initialisation point.
All endpoints import `db` from here and call collection helpers directly.

LAZY INIT: db is NOT initialised at import time.  This allows the backend
process to start and bind its port even when firebase_credentials.json is
missing, so the /health endpoint always responds and the frontend login
page can display while credentials are being configured.
"""
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client

from app.core.config import settings


# ── Credential discovery ──────────────────────────────────────

def _find_credentials() -> str:
    """
    Search order:
    1. Env var FIREBASE_CREDENTIALS_PATH (absolute or relative to cwd)
    2. Next to the exe (PyInstaller production)
    3. backend/ folder (development)

    Raises a descriptive FileNotFoundError listing every path tried.
    """
    env_path = settings.firebase_credentials_path
    if os.path.isabs(env_path) and os.path.exists(env_path):
        return env_path

    candidates = [
        Path(env_path),
        Path(sys.executable).parent / "firebase_credentials.json",
        Path(__file__).parent.parent.parent / "firebase_credentials.json",
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    searched = "\n  ".join(str(p.resolve()) for p in candidates)
    raise FileNotFoundError(
        "firebase_credentials.json not found.\n\n"
        "Searched:\n"
        f"  {searched}\n\n"
        "Fix: place firebase_credentials.json next to the executable, "
        "or set FIREBASE_CREDENTIALS_PATH in the .env file."
    )


def _init_firestore() -> Client:
    if not firebase_admin._apps:
        cred_path = _find_credentials()
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Lazy client ───────────────────────────────────────────────

_db: Client | None = None


def _get_db() -> Client:
    """Return the shared Firestore client, initialising it on first call."""
    global _db
    if _db is None:
        _db = _init_firestore()
    return _db


class _LazyDB:
    """
    Proxy that forwards all attribute / method access to the real Firestore
    client.  Backwards-compatible with code that does:
        from app.core.firestore_client import db
        db.collection(...)
    """
    def __getattr__(self, name):
        return getattr(_get_db(), name)

    def collection(self, *args, **kwargs):
        return _get_db().collection(*args, **kwargs)

    def collection_group(self, *args, **kwargs):
        return _get_db().collection_group(*args, **kwargs)

    def transaction(self, *args, **kwargs):
        return _get_db().transaction(*args, **kwargs)

    def batch(self, *args, **kwargs):
        return _get_db().batch(*args, **kwargs)


db: Client = _LazyDB()  # type: ignore[assignment]


# ── Collection shortcuts ──────────────────────────────────────

def col(name: str):
    return _get_db().collection(name)


def accounts():
    return col("accounts")


def subscriptions():
    return col("subscriptions")


def clients():
    return col("clients")


def client_subs(client_name: str):
    return clients().document(client_name).collection("subscriptions")


def attendance(date_str: str):
    return col("attendance_logs").document(date_str).collection("logs")


def sales(date_str: str):
    return col("sale_logs").document(date_str).collection("sales")


def sale_items(date_str: str, sales_uid: str):
    return sales(date_str).document(sales_uid).collection("items")


def items():
    return col("item_catalogue")


def system_state():
    return col("system_state")


# ── Counter helpers ───────────────────────────────────────────

def next_uid(counter_name: str) -> int:
    """Atomic counter increment using Firestore transactions."""
    ref = system_state().document("counters")

    @firestore.transactional
    def _increment(transaction, ref):
        snap = ref.get(transaction=transaction)
        current = snap.to_dict().get(counter_name, 0) if snap.exists else 0
        new_val = current + 1
        transaction.set(ref, {counter_name: new_val}, merge=True)
        return new_val

    return _increment(_get_db().transaction(), ref)


def next_attendance_uid() -> int:
    return next_uid("attendance_counter")


def next_sales_uid() -> int:
    return next_uid("sales_counter")