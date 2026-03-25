from datetime import datetime
from pydantic import BaseModel


class ClientCreate(BaseModel):
    client_name: str
    client_duration: str
    client_budget: float = 0.0


class ClientUpdate(BaseModel):
    client_duration: str | None = None
    client_status: bool | None = None
    client_budget: float | None = None


class ClientReEnroll(BaseModel):
    client_duration: str


class ClientRead(BaseModel):
    client_name: str
    client_duration: str
    client_status: bool
    client_current_uid_log: int
    client_current_sale_uid: int
    client_budget: float
    last_enrolled_at: datetime | None

    model_config = {"from_attributes": True}