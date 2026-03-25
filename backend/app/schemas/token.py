from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account_type: str


class TokenData(BaseModel):
    account_name: str
    account_type: str
