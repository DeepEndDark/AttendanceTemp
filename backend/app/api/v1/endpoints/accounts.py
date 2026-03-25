from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.core.security import hash_password
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/", response_model=list[AccountRead])
def list_accounts(_: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(Account).all()


@router.post("/", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, _: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(Account).filter(Account.account_name == payload.account_name).first():
        raise HTTPException(status_code=409, detail="Account name already exists")
    account = Account(
        account_name=payload.account_name,
        account_type=payload.account_type,
        hashed_password=hash_password(payload.password),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_name}", response_model=AccountRead)
def update_account(
    account_name: str,
    payload: AccountUpdate,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    account = db.query(Account).filter(Account.account_name == account_name).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if payload.account_type is not None:
        account.account_type = payload.account_type
    if payload.password is not None:
        account.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_name: str,
    current_user: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if account_name == current_user.account_name:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    account = db.query(Account).filter(Account.account_name == account_name).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
