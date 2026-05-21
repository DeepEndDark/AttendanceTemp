from pydantic import BaseModel


class TimeInRequest(BaseModel):
    client_name: str


class TimeOutRequest(BaseModel):
    client_name: str


class AttendanceLogRead(BaseModel):
    log_uid: int
    log_date: str
    client_name: str
    time_in: str
    time_out: str | None
    expiry_warning: bool = False
    days_remaining: int = 0
