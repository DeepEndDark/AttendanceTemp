from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import require_admin
from app.core.firestore_client import accounts
from app.core.security import hash_password
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/", response_model=list[AccountRead])
def list_accounts(_: TokenData = Depends(require_admin)):
    return [AccountRead(**d.to_dict()) for d in accounts().stream()]


@router.post("/", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, _: TokenData = Depends(require_admin)):
    ref = accounts().document(payload.account_name)
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Account already exists")
    data = {
        "account_name": payload.account_name,
        "account_type": payload.account_type,
        "hashed_password": hash_password(payload.password),
    }
    ref.set(data)
    return AccountRead(account_name=payload.account_name, account_type=payload.account_type)


@router.patch("/{account_name}", response_model=AccountRead)
def update_account(account_name: str, payload: AccountUpdate,
                   _: TokenData = Depends(require_admin)):
    ref = accounts().document(account_name)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Account not found")
    updates = {}
    if payload.account_type:
        updates["account_type"] = payload.account_type
    if payload.password:
        updates["hashed_password"] = hash_password(payload.password)
    ref.update(updates)
    data = ref.get().to_dict()
    return AccountRead(account_name=data["account_name"], account_type=data["account_type"])


@router.delete("/{account_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_name: str, current_user: TokenData = Depends(require_admin)):
    if account_name == current_user.account_name:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    ref = accounts().document(account_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Account not found")
    ref.delete()
