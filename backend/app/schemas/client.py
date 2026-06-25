from pydantic import BaseModel


class ClientCreate(BaseModel):
    client_name: str
    contact_number: str | None = None
    address: str | None = None
    subscription_name: str


class ClientUpdate(BaseModel):
    contact_number: str | None = None
    address: str | None = None
    client_status: bool | None = None


class ClientReEnroll(BaseModel):
    subscription_name: str


class ClientSubRead(BaseModel):
    id: str
    subscription_name: str
    subscribed_at: str
    expires_at: str
    days_remaining: int
    trainer_days_remaining: int
    trainer_hardcap_remaining: int
    is_active: bool


class ClientRead(BaseModel):
    client_uid: int
    client_name: str
    contact_number: str | None
    address: str | None
    client_status: bool
    client_current_uid_log: int | None = None
    client_current_sale_uid: int | None = None
    client_days_remaining: int
    client_trainer_days_remaining: int
    client_locker_days_remaining: int          # total across all lockers (legacy compat)
    locker_number: int | None                  # primary locker (legacy compat)
    lockers: list[dict] = []                   # [{locker_number, days_remaining, expires_at}]
    created_at: str | None
    last_enrolled_at: str | None
    last_plan_expires_at: str | None
    active_subscription_names: list[str] = []   # plan(s) currently active
    fingerprint_enrolled: bool


class ClientEnrollResponse(BaseModel):
    client: ClientRead
    warning: str | None = None