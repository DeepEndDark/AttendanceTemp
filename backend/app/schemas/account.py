from typing import Literal
from pydantic import BaseModel

class AccountCreate(BaseModel):
    account_name: str
    account_type: Literal["admin", "sales"]
    password: str

class AccountRead(BaseModel):
    account_name: str
    account_type: str

class AccountUpdate(BaseModel):
    account_type: Literal["admin", "sales"] | None = None
    password: str | None = None
