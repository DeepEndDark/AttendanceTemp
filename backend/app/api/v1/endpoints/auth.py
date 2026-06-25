from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.firestore_client import accounts
from app.core.security import create_access_token, verify_password, hash_password
from app.schemas.token import Token

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Hardcoded local-admin "break glass" credential ────────────
# This account exists ONLY to let an administrator configure Firebase
# when Firestore itself is unreachable (so normal /auth/login can't work).
# It is intentionally fixed — this system runs on a single, non-exposed
# gym management machine and is not meant to be changed per-deployment.
# It grants access ONLY to the /admin/apply-firebase-config endpoint —
# nothing else — via the "local_admin" account_type on its token.
_LOCAL_ADMIN_USERNAME = "admin"
_LOCAL_ADMIN_PASSWORD_HASH = hash_password("admin123")


@router.post("/local-login", response_model=Token)
def local_login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Bootstrap login that does NOT touch Firestore.  Used only to unlock
    the Firebase setup panel when normal login is unavailable because
    credentials are missing or the DB can't be reached.
    """
    if form_data.username != _LOCAL_ADMIN_USERNAME or \
       not verify_password(form_data.password, _LOCAL_ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token({
        "sub": _LOCAL_ADMIN_USERNAME,
        "account_type": "local_admin",
    })
    return Token(access_token=token, account_type="local_admin")


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    doc = accounts().document(form_data.username).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})
    data = doc.to_dict()
    if not verify_password(form_data.password, data["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token({
        "sub": data["account_name"],
        "account_type": data["account_type"],
    })
    return Token(access_token=token, account_type=data["account_type"])