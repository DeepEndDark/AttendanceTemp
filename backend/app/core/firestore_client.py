"""
Firestore client — single initialisation point.
All endpoints import `fs` from here and call collection helpers directly.
"""
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client

from app.core.config import settings


def _find_credentials() -> str:
    """
    Search order:
    1. Env var FIREBASE_CREDENTIALS_PATH (absolute or relative to cwd)
    2. Next to the exe (PyInstaller production)
    3. backend/ folder (development)
    """
    # Explicit env path
    env_path = settings.firebase_credentials_path
    if os.path.isabs(env_path) and os.path.exists(env_path):
        return env_path

    candidates = [
        Path(env_path),                                  # relative to cwd
        Path(sys.executable).parent / "firebase_credentials.json",  # next to exe
        Path(__file__).parent.parent.parent / "firebase_credentials.json",  # backend/
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    raise FileNotFoundError(
        "firebase_credentials.json not found. "
        "Place it next to the executable or in the backend/ folder."
    )


def init_firestore() -> Client:
    if not firebase_admin._apps:
        cred_path = _find_credentials()
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Module-level client ───────────────────────────────────────
db: Client = init_firestore()


# ── Collection shortcuts ──────────────────────────────────────

def col(name: str):
    return db.collection(name)


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


def daily_reports():
    return col("daily_reports")


def monthly_reports():
    return col("monthly_reports")


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

    return _increment(db.transaction(), ref)


def next_attendance_uid() -> int:
    return next_uid("attendance_counter")


def next_sales_uid() -> int:
    return next_uid("sales_counter")
