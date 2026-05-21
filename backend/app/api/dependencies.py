from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from app.core.security import decode_token
from app.schemas.token import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        name: str = payload.get("sub")
        role: str = payload.get("account_type")
        if not name or not role:
            raise exc
        return TokenData(account_name=name, account_type=role)
    except JWTError:
        raise exc


def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_any(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    return current_user
