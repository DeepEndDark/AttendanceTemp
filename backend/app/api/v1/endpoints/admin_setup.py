"""
admin_setup.py

Firebase setup-recovery endpoint.  Reachable only via a token issued by
/auth/local-login (account_type == "local_admin"), which works even when
Firestore is completely unreachable — this is the "break glass" path to
get the system configured for the first time or to fix a bad credentials
file without needing shell/file access to the machine.
"""
import json
import os
import shutil
import sys

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.api.dependencies import require_local_admin
from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin-setup"])


def _credentials_target_path() -> str:
    """
    Where the credentials file should live — same resolution order as
    firestore_client._find_credentials(), but returns a single write target
    (next to the exe in production, next to backend/ in development).
    """
    env_path = settings.firebase_credentials_path
    if os.path.isabs(env_path):
        return env_path
    exe_dir = os.path.dirname(sys.executable)
    return os.path.join(exe_dir, "firebase_credentials.json")


def _env_file_path() -> str:
    exe_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(exe_dir, ".env")
    if os.path.exists(candidate):
        return candidate
    # Fall back to backend/.env for development runs
    dev_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")
    )
    return dev_path


@router.post("/apply-firebase-config")
async def apply_firebase_config(
    file: UploadFile = File(...),
    _admin=Depends(require_local_admin),
):
    """
    Accepts a Firebase service-account JSON, validates it, saves it to the
    correct path, updates .env, and resets the cached Firestore client so
    the next request re-initialises against the new credentials.
    """
    raw = await file.read()

    # Validate it's a real service-account file before writing anything
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="File is not valid JSON")

    if parsed.get("type") != "service_account":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='File is missing "type": "service_account" — '
                   "this doesn't look like a Firebase service account key",
        )

    dest = _credentials_target_path()
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(raw)

    # Update .env so future restarts pick up the same path
    env_path = _env_file_path()
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
    new_lines, found = [], False
    for line in lines:
        if line.startswith("FIREBASE_CREDENTIALS_PATH="):
            new_lines.append(f"FIREBASE_CREDENTIALS_PATH={dest}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"FIREBASE_CREDENTIALS_PATH={dest}\n")
    with open(env_path, "w") as f:
        f.writelines(new_lines)

    # Reset the cached Firestore client so the new credentials take effect
    # immediately, without restarting the backend process.
    import app.core.firestore_client as fc
    fc._db = None
    import firebase_admin
    for app_name in list(firebase_admin._apps.keys()):
        firebase_admin.delete_app(firebase_admin.get_app(app_name))

    # Try connecting right away so we can report success/failure clearly
    try:
        fc._get_db()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Credentials saved but connection failed: {exc}",
        )

    # Seed the default admin account now that Firestore is reachable
    try:
        from app.core.security import hash_password
        ref = fc.accounts().document("admin")
        if not ref.get().exists:
            ref.set({
                "account_name":    "admin",
                "account_type":    "admin",
                "hashed_password": hash_password("admin123"),
            })
    except Exception:
        pass  # non-fatal — connection already verified above

    return {"status": "ok", "message": "Firebase configured successfully"}