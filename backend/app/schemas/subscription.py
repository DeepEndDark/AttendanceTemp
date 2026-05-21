from pydantic import BaseModel

class SubscriptionCreate(BaseModel):
    subscription_name: str
    duration_days: int
    price: float
    has_trainer: bool = False
    trainer_duration_days: int = 0
    trainer_hardcap_days: int = 0

class SubscriptionUpdate(BaseModel):
    duration_days: int | None = None
    price: float | None = None
    has_trainer: bool | None = None
    trainer_duration_days: int | None = None
    trainer_hardcap_days: int | None = None

class SubscriptionRead(BaseModel):
    subscription_name: str
    duration_days: int
    price: float
    has_trainer: bool
    trainer_duration_days: int
    trainer_hardcap_days: int
