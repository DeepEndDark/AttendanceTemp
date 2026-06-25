from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import (
    clients, client_subs, subscriptions, db,
    next_sales_uid, next_uid, system_state
)
from app.schemas.client import (
    ClientCreate, ClientRead, ClientUpdate,
    ClientReEnroll, ClientEnrollResponse, ClientSubRead
)
from app.schemas.token import TokenData

router = APIRouter(prefix="/clients", tags=["clients"])


# ── Helpers ───────────────────────────────────────────────────

def _recalc_totals(client_name: str) -> dict:
    active = list(
        client_subs(client_name).where("is_active", "==", True).stream())
    total_days    = 0
    total_trainer = 0
    expiry_dates  = []
    plan_names    = []
    for s in active:
        d = s.to_dict()
        total_days    += d.get("days_remaining", 0)
        total_trainer += d.get("trainer_days_remaining", 0)
        exp = d.get("expires_at", "")
        if exp:
            expiry_dates.append(exp)
        name = d.get("subscription_name")
        if name and name not in plan_names:
            plan_names.append(name)
    return {
        "client_days_remaining":         total_days,
        "client_trainer_days_remaining": total_trainer,
        "last_plan_expires_at":          max(expiry_dates) if expiry_dates else None,
        "active_subscription_names":    plan_names,
    }


def _doc_to_read(d: dict) -> ClientRead:
    lockers = d.get("lockers", [])
    # Legacy: if old single-locker fields exist and lockers list is empty, migrate
    if not lockers and d.get("locker_number"):
        lockers = [{
            "locker_number":    d["locker_number"],
            "days_remaining":   d.get("client_locker_days_remaining", 0),
            "expires_at":       None,
        }]
    return ClientRead(
        client_uid=d.get("client_uid", 0),
        client_name=d["client_name"],
        contact_number=d.get("contact_number"),
        address=d.get("address"),
        client_status=d.get("client_status", False),
        client_current_uid_log=d.get("client_current_uid_log"),
        client_current_sale_uid=d.get("client_current_sale_uid"),
        client_days_remaining=d.get("client_days_remaining", 0),
        client_trainer_days_remaining=d.get(
            "client_trainer_days_remaining", 0),
        client_locker_days_remaining=sum(
            l.get("days_remaining", 0) for l in lockers),
        locker_number=lockers[0]["locker_number"] if lockers else None,
        lockers=lockers,
        created_at=d.get("created_at"),
        last_enrolled_at=d.get("last_enrolled_at"),
        last_plan_expires_at=d.get("last_plan_expires_at"),
        active_subscription_names=d.get("active_subscription_names", []),
        fingerprint_enrolled=bool(d.get("fingerprint_template")),
    )


def _touch_sale_date(date_str: str):
    db.collection("sale_logs").document(date_str).set(
        {"_date": date_str}, merge=True)


def _create_subscription_sale(
        client_name: str, sub_name: str, price: float) -> None:
    """Auto-create a closed sale log when a subscription is enrolled."""
    today = date.today().isoformat()
    uid   = next_sales_uid()
    _touch_sale_date(today)
    sale_ref = (db.collection("sale_logs")
                  .document(today)
                  .collection("sales")
                  .document(str(uid)))
    sale_ref.set({
        "sales_uid":   uid,
        "client_name": client_name,
        "sale_status": "closed",
        "total_price": round(price, 2),
        "sale_date":   today,
    })
    sale_ref.collection("items").add({
        "item_name":        sub_name,
        "item_qty":         1,
        "item_total_price": round(price, 2),
        "is_subscription":  True,
        "is_locker":        False,
    })


# ── List / search ─────────────────────────────────────────────

@router.get("/", response_model=list[ClientRead])
def list_clients(_: TokenData = Depends(require_any)):
    return [_doc_to_read(d.to_dict()) for d in clients().stream()]


@router.get("/active", response_model=list[ClientRead])
def list_active_clients(_: TokenData = Depends(require_any)):
    return [_doc_to_read(d.to_dict())
            for d in clients().where("client_status", "==", True).stream()]


@router.get("/enroll-fingerprint/progress")
def enroll_progress(_: TokenData = Depends(require_any)):
    """Returns current enrollment scan count: 0=idle, 1-3=scanning, -1=failed."""
    from app.core.fingerprint import get_enroll_progress
    return {"progress": get_enroll_progress()}


@router.get("/{client_name}", response_model=ClientRead)
def get_client(client_name: str, _: TokenData = Depends(require_any)):
    doc = clients().document(client_name).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")
    return _doc_to_read(doc.to_dict())


@router.get("/{client_name}/subscriptions",
            response_model=list[ClientSubRead])
def get_client_subscriptions(client_name: str,
                              _: TokenData = Depends(require_any)):
    result = []
    for s in (client_subs(client_name)
              .order_by("subscribed_at").stream()):
        d = s.to_dict()
        result.append(ClientSubRead(
            id=s.id,
            subscription_name=d["subscription_name"],
            subscribed_at=d["subscribed_at"],
            expires_at=d["expires_at"],
            days_remaining=d.get("days_remaining", 0),
            trainer_days_remaining=d.get("trainer_days_remaining", 0),
            trainer_hardcap_remaining=d.get("trainer_hardcap_remaining", 0),
            is_active=d.get("is_active", False),
        ))
    return result


# ── Create ────────────────────────────────────────────────────

@router.post("/", response_model=ClientEnrollResponse,
             status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate,
                  _: TokenData = Depends(require_any)):
    ref = clients().document(payload.client_name)
    if ref.get().exists:
        raise HTTPException(status_code=409,
                            detail="Client already exists")

    sub_doc = subscriptions().document(payload.subscription_name).get()
    if not sub_doc.exists:
        raise HTTPException(status_code=404,
                            detail="Subscription plan not found")
    plan = sub_doc.to_dict()

    now    = datetime.now(timezone.utc)
    today  = date.today()
    # Registration day = Day 1
    expires = (today + timedelta(
        days=plan["duration_days"] - 1)).isoformat()

    client_uid = next_uid("client_counter")

    client_data = {
        "client_uid":                    client_uid,
        "client_name":                   payload.client_name,
        "contact_number":                payload.contact_number,
        "address":                       payload.address,
        "client_status":                 False,
        "client_current_uid_log":        None,
        "client_current_sale_uid":       None,
        "client_days_remaining":         plan["duration_days"],
        "client_trainer_days_remaining": plan.get(
            "trainer_duration_days", 0),
        "client_locker_days_remaining":  0,
        "locker_number":                 None,
        "lockers":                       [],
        "created_at":                    now.isoformat(),
        "last_enrolled_at":              now.isoformat(),
        "last_plan_expires_at":          expires,
        "active_subscription_names":    [payload.subscription_name],
        "fingerprint_template":          None,
    }
    ref.set(client_data)

    # First subscription record
    client_subs(payload.client_name).add({
        "subscription_name":        payload.subscription_name,
        "subscribed_at":            today.isoformat(),
        "expires_at":               expires,
        "days_remaining":           plan["duration_days"],
        "trainer_days_remaining":   plan.get("trainer_duration_days", 0),
        "trainer_hardcap_remaining": plan.get("trainer_hardcap_days", 0),
        "has_trainer":              plan.get("has_trainer", False),
        "is_active":                True,
    })

    _create_subscription_sale(
        payload.client_name, payload.subscription_name, plan["price"])

    return ClientEnrollResponse(client=_doc_to_read(client_data))


# ── Re-enroll ─────────────────────────────────────────────────

@router.post("/{client_name}/re-enroll",
             response_model=ClientEnrollResponse)
def re_enroll(client_name: str, payload: ClientReEnroll,
              _: TokenData = Depends(require_any)):
    ref = clients().document(client_name)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")

    sub_doc = subscriptions().document(payload.subscription_name).get()
    if not sub_doc.exists:
        raise HTTPException(status_code=404,
                            detail="Subscription plan not found")
    plan = sub_doc.to_dict()

    now     = datetime.now(timezone.utc)
    today   = date.today()
    expires = (today + timedelta(
        days=plan["duration_days"] - 1)).isoformat()

    active_subs = list(
        client_subs(client_name).where("is_active", "==", True).stream())
    warning = None
    if active_subs:
        warning = (f"Client already has {len(active_subs)} active "
                   f"subscription(s). Days will be added to existing total.")

    client_subs(client_name).add({
        "subscription_name":        payload.subscription_name,
        "subscribed_at":            today.isoformat(),
        "expires_at":               expires,
        "days_remaining":           plan["duration_days"],
        "trainer_days_remaining":   plan.get("trainer_duration_days", 0),
        "trainer_hardcap_remaining": plan.get("trainer_hardcap_days", 0),
        "has_trainer":              plan.get("has_trainer", False),
        "is_active":                True,
    })

    totals = _recalc_totals(client_name)
    ref.update({**totals, "last_enrolled_at": now.isoformat()})

    _create_subscription_sale(
        client_name, payload.subscription_name, plan["price"])

    updated = ref.get().to_dict()
    return ClientEnrollResponse(
        client=_doc_to_read(updated), warning=warning)


# ── Update / Delete (admin only) ──────────────────────────────

@router.patch("/{client_name}", response_model=ClientRead)
def update_client(client_name: str, payload: ClientUpdate,
                  _: TokenData = Depends(require_admin)):
    ref = clients().document(client_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = {k: v for k, v in payload.model_dump().items()
               if v is not None}
    if updates:
        ref.update(updates)
    return _doc_to_read(ref.get().to_dict())


@router.delete("/{client_name}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_name: str,
                  _: TokenData = Depends(require_admin)):
    ref = clients().document(client_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Client not found")
    from app.core.fingerprint import remove_from_cache
    remove_from_cache(client_name)
    # Delete subscription subcollection docs first (Firestore doesn't cascade)
    batch = db.batch()
    batch_count = 0
    for sub_doc in client_subs(client_name).stream():
        batch.delete(sub_doc.reference)
        batch_count += 1
        if batch_count >= 500:   # Firestore batch limit
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count:
        batch.commit()
    ref.delete()


# ── Deduct trainer ────────────────────────────────────────────

@router.post("/{client_name}/deduct-trainer",
             response_model=ClientRead)
def deduct_trainer(client_name: str,
                   _: TokenData = Depends(require_any)):
    ref = clients().document(client_name)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")

    # Determine deduction method from settings
    settings = system_state().document("settings").get()
    method   = "fifo"
    if settings.exists:
        method = settings.to_dict().get(
            "trainer_deduction_method", "fifo")

    if doc.to_dict().get("client_trainer_days_remaining", 0) <= 0:
        raise HTTPException(status_code=400,
                            detail="No trainer days remaining")

    # FIFO: oldest active sub with trainer days > 0
    active = list(
        client_subs(client_name)
        .where("is_active", "==", True)
        .where("trainer_days_remaining", ">", 0)
        .order_by("subscribed_at")
        .limit(1)
        .stream()
    )
    if not active:
        raise HTTPException(status_code=400,
                            detail="No trainer days available")

    target = active[0]
    target.reference.update({
        "trainer_days_remaining":
            target.to_dict()["trainer_days_remaining"] - 1
    })

    totals = _recalc_totals(client_name)
    ref.update(totals)
    return _doc_to_read(ref.get().to_dict())


# ── Fingerprint enroll ────────────────────────────────────────

@router.post("/{client_name}/enroll-fingerprint",
             response_model=ClientRead)
def enroll_fingerprint(client_name: str,
                       _: TokenData = Depends(require_any)):
    ref = clients().document(client_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Client not found")

    from app.core.fingerprint import (
        enroll_finger, update_template_cache, SCANNER_AVAILABLE
    )
    if not SCANNER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Fingerprint scanner not available")

    template = enroll_finger(skip_name=client_name)
    if not template:
        raise HTTPException(
            status_code=500,
            detail="Fingerprint enrollment failed. Please try again.")

    if template.startswith("DUPLICATE:"):
        existing = template.split(":", 1)[1]
        raise HTTPException(
            status_code=409,
            detail=f"This fingerprint is already registered to '{existing}'. "
                   f"Duplicate fingerprints are not allowed.")

    ref.update({"fingerprint_template": template})
    update_template_cache(client_name, template)
    return _doc_to_read(ref.get().to_dict())