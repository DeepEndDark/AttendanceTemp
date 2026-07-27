from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import subscriptions
from app.schemas.subscription import SubscriptionCreate, SubscriptionRead, SubscriptionUpdate
from pydantic import BaseModel
from app.schemas.token import TokenData

class RenamePayload(BaseModel):
    new_name: str

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

def get_live_plan_holders() -> dict[str, list[str]]:
    """
    Recomputes plan membership directly from Firestore rather than the
    denormalized `active_subscription_names` field on client docs: a
    collection_group query across every client's `subscriptions`
    subcollection, filtered to `is_active == True`.

    Shared by the `/active-by-client` endpoint below (for the frontend's
    live cross-check) and by the PDF report export in reports.py, so both
    the on-screen plan filter and the exported report are checked against
    the same live truth rather than the export trusting a field that
    could have drifted.

    Requires a Firestore collection-group index on `subscriptions` for the
    `is_active` field (see firestore.indexes.json) — collection_group
    queries don't get Firestore's automatic single-field indexing the way
    plain collection queries do.

    Returns: { "PlanName": ["client1", "client2", ...], ... }
    """
    from app.core.firestore_client import db

    by_plan: dict[str, list[str]] = {}

    for sub_doc in db.collection_group("subscriptions") \
        .where("is_active", "==", True).stream():
        data = sub_doc.to_dict()
        plan_name = data.get("subscription_name")
        if not plan_name:
            continue
        # Parent of a subscription doc is the client's subcollection;
        # its parent is the client document itself.
        client_name = sub_doc.reference.parent.parent.id
        by_plan.setdefault(plan_name, [])
        if client_name not in by_plan[plan_name]:
            by_plan[plan_name].append(client_name)

    return by_plan


@router.get("/active-by-client")
def get_active_subscriptions_by_client(_: TokenData = Depends(require_any)):
    """
    Secondary/authoritative check for plan filtering across the app.

    The plan filter (Reports, Client List, Attendance, Sales) primarily
    reads each client's cached `active_subscription_names` field for
    speed — but that field is denormalized and only updated at specific
    moments (enroll, re-enroll, the nightly tick). If any of those update
    paths is ever missed, or a doc is edited directly, the cached field
    can drift from what the subscriptions subcollection actually says.

    The frontend can use this to validate the cached field, or as a
    fallback if a discrepancy is suspected.
    """
    return get_live_plan_holders()


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
def delete_subscription(name: str, force: bool = Query(False),
                        _: TokenData = Depends(require_admin)):
    """
    Deletes a plan from the catalog only. Existing holders are unaffected —
    each client's subscription record is a denormalized copy made at
    enroll time, so it keeps ticking down and expiring normally even
    after the catalog entry is gone.

    By default this refuses to delete a plan that still has active
    holders, so an admin doesn't do this silently. Pass ?force=true to
    delete anyway (e.g. plan was created by mistake, or holders are
    being migrated off it deliberately).
    """
    ref = subscriptions().document(name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if not force:
        from app.core.firestore_client import db
        # Reuses the existing is_active collection_group index and filters
        # by plan name in Python, rather than adding a second composite
        # index just for this check.
        holder_count = sum(
            1 for doc in db.collection_group("subscriptions")
                .where("is_active", "==", True).stream()
            if doc.to_dict().get("subscription_name") == name
        )
        if holder_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{holder_count} client(s) currently hold this plan. "
                    "Deleting it only removes it from the catalog — "
                    "existing holders keep their subscription until it "
                    "expires normally. Pass force=true to delete anyway."
                ),
            )

    ref.delete()


@router.post("/{name}/rename", response_model=SubscriptionRead)
def rename_subscription(name: str,
                        payload: RenamePayload,
                        _: TokenData = Depends(require_admin)):
    """
    Rename a subscription plan.
    Creates new doc with new name, copies data, deletes old.
    Updates subscription_name field on all client sub records.
    """
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name required")
    if new_name == name:
        raise HTTPException(status_code=400, detail="New name is same as current")

    old_ref = subscriptions().document(name)
    old_doc = old_ref.get()
    if not old_doc.exists:
        raise HTTPException(status_code=404, detail="Subscription not found")

    new_ref = subscriptions().document(new_name)
    if new_ref.get().exists:
        raise HTTPException(status_code=409, detail="Name already taken")

    from app.core.firestore_client import client_subs, clients as clients_col
    data = old_doc.to_dict()
    data["subscription_name"] = new_name
    new_ref.set(data)
    old_ref.delete()

    # Update all client subscription records referencing old name using batch writes
    from app.core.firestore_client import client_subs, clients as clients_col, db
    batch = db.batch()
    batch_count = 0
    for client_doc in clients_col().stream():
        cname = client_doc.id
        for sub_doc in client_subs(cname).where(
                "subscription_name", "==", name).stream():
            batch.update(sub_doc.reference, {"subscription_name": new_name})
            batch_count += 1
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
    if batch_count:
        batch.commit()

    return _to_read(data)