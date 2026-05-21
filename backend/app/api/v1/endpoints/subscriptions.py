from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import subscriptions
from app.schemas.subscription import SubscriptionCreate, SubscriptionRead, SubscriptionUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _to_read(d: dict) -> SubscriptionRead:
    return SubscriptionRead(
        subscription_name=d["subscription_name"],
        duration_days=d["duration_days"],
        price=d["price"],
        has_trainer=d.get("has_trainer", False),
        trainer_duration_days=d.get("trainer_duration_days", 0),
        trainer_hardcap_days=d.get("trainer_hardcap_days", 0),
    )


@router.get("/", response_model=list[SubscriptionRead])
def list_subscriptions(_: TokenData = Depends(require_any)):
    return [_to_read(d.to_dict()) for d in subscriptions().stream()]


@router.get("/{name}", response_model=SubscriptionRead)
def get_subscription(name: str, _: TokenData = Depends(require_any)):
    doc = subscriptions().document(name).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return _to_read(doc.to_dict())


@router.post("/", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
def create_subscription(payload: SubscriptionCreate, _: TokenData = Depends(require_admin)):
    ref = subscriptions().document(payload.subscription_name)
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Subscription already exists")
    data = payload.model_dump()
    ref.set(data)
    return _to_read(data)


@router.patch("/{name}", response_model=SubscriptionRead)
def update_subscription(name: str, payload: SubscriptionUpdate,
                        _: TokenData = Depends(require_admin)):
    ref = subscriptions().document(name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Subscription not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    ref.update(updates)
    return _to_read(ref.get().to_dict())


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(name: str, _: TokenData = Depends(require_admin)):
    ref = subscriptions().document(name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Subscription not found")
    ref.delete()
