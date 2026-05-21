from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.firestore_client import accounts
from app.core.security import create_access_token, verify_password
from app.schemas.token import Token

router = APIRouter(prefix="/auth", tags=["auth"])


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
