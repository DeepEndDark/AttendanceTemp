from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import (
    clients, db, next_sales_uid, system_state
)
from app.schemas.token import TokenData

router = APIRouter(prefix="/lockers", tags=["lockers"])

SETTINGS_DOC = "settings"


def _get_settings() -> dict:
    doc = system_state().document(SETTINGS_DOC).get()
    if doc.exists:
        return doc.to_dict()
    return {
        "total_lockers":           0,
        "locker_price":            0.0,
        "locker_rental_days":      30,
        "trainer_deduction_method": "fifo",
    }


def _write_sale_log(client_name: str, price: float):
    """Auto-create a closed sale log for a locker rental."""
    today   = date.today().isoformat()
    uid     = next_sales_uid()
    # Touch parent date doc
    db.collection("sale_logs").document(today).set(
        {"_date": today}, merge=True)
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
        "item_name":        "Locker Rental",
        "item_qty":         1,
        "item_total_price": round(price, 2),
        "is_subscription":  False,
        "is_locker":        True,
    })


def _lowest_available_locker(total: int) -> int | None:
    """Return lowest locker number not currently assigned."""
    rented = set()
    for c in clients().where("locker_number", "!=", None).stream():
        n = c.to_dict().get("locker_number")
        if n:
            rented.add(n)
    for i in range(1, total + 1):
        if i not in rented:
            return i
    return None


# ── Schemas ───────────────────────────────────────────────────

class LockerSettings(BaseModel):
    total_lockers:            int | None = None
    locker_price:             float | None = None
    locker_rental_days:       int | None = None
    trainer_deduction_method: str | None = None


class LockerRentRequest(BaseModel):
    client_name: str


class LockerAssignRequest(BaseModel):
    client_name:   str
    locker_number: int


class LockerAvailability(BaseModel):
    total:       int
    rented:      int
    available:   int
    price:       float
    rental_days: int


# ── Settings ──────────────────────────────────────────────────

@router.get("/settings")
def get_settings(_: TokenData = Depends(require_any)):
    return _get_settings()


@router.patch("/settings")
def update_settings(payload: LockerSettings,
                    _: TokenData = Depends(require_admin)):
    ref     = system_state().document(SETTINGS_DOC)
    updates = {k: v for k, v in payload.model_dump().items()
               if v is not None}
    ref.set(updates, merge=True)
    return ref.get().to_dict()


# ── Availability ──────────────────────────────────────────────

@router.get("/available", response_model=LockerAvailability)
def get_availability(_: TokenData = Depends(require_any)):
    s      = _get_settings()
    total  = s.get("total_lockers", 0)
    rented = len(list(
        clients().where("locker_number", "!=", None).stream()))
    return LockerAvailability(
        total=total,
        rented=rented,
        available=max(0, total - rented),
        price=s.get("locker_price", 0.0),
        rental_days=s.get("locker_rental_days", 30),
    )


# ── FIFO self-service rent ────────────────────────────────────

@router.post("/rent")
def rent_locker(payload: LockerRentRequest,
                _: TokenData = Depends(require_any)):
    s           = _get_settings()
    total       = s.get("total_lockers", 0)
    rental_days = s.get("locker_rental_days", 30)
    price       = s.get("locker_price", 0.0)

    client_ref = clients().document(payload.client_name)
    client_doc = client_ref.get()
    if not client_doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")
    client_data = client_doc.to_dict()

    today   = date.today()
    expires = (today + timedelta(days=rental_days - 1)).isoformat()

    current_locker = client_data.get("locker_number")
    current_days   = client_data.get("client_locker_days_remaining", 0)

    if current_locker is not None:
        # Additive — same locker, more days
        client_ref.update({
            "client_locker_days_remaining": current_days + rental_days
        })
        assigned = current_locker
    else:
        assigned = _lowest_available_locker(total)
        if assigned is None:
            raise HTTPException(status_code=400,
                                detail="No lockers available")
        client_ref.update({
            "locker_number":               assigned,
            "client_locker_days_remaining": rental_days,
        })

    db.collection("locker_rentals").add({
        "client_name":       payload.client_name,
        "locker_number":     assigned,
        "rented_at":         today.isoformat(),
        "expires_at":        expires,
        "days_added":        rental_days,
        "assigned_by_admin": False,
    })

    _write_sale_log(payload.client_name, price)

    return {
        "client_name":                payload.client_name,
        "locker_number":              assigned,
        "days_added":                 rental_days,
        "expires_at":                 expires,
        "client_locker_days_remaining":
            client_ref.get().to_dict().get("client_locker_days_remaining"),
    }


# ── Admin manual assign ───────────────────────────────────────

@router.post("/assign")
def assign_locker(payload: LockerAssignRequest,
                  _: TokenData = Depends(require_admin)):
    """
    Admin assigns a specific locker number to a client.
    Additive if client already has a locker (same locker, more days).
    Rejected if the chosen number is held by a different client.
    """
    s           = _get_settings()
    total       = s.get("total_lockers", 0)
    rental_days = s.get("locker_rental_days", 30)
    price       = s.get("locker_price", 0.0)

    if payload.locker_number < 1 or payload.locker_number > total:
        raise HTTPException(
            status_code=400,
            detail=f"Locker #{payload.locker_number} does not exist "
                   f"(total lockers: {total})")

    client_ref = clients().document(payload.client_name)
    if not client_ref.get().exists:
        raise HTTPException(status_code=404, detail="Client not found")
    client_data = client_ref.get().to_dict()

    # Check if chosen locker is already taken by someone else
    for other in (clients()
                  .where("locker_number", "==", payload.locker_number)
                  .stream()):
        if other.id != payload.client_name:
            raise HTTPException(
                status_code=409,
                detail=f"Locker #{payload.locker_number} is already "
                       f"assigned to '{other.id}'")

    today        = date.today()
    expires      = (today + timedelta(days=rental_days - 1)).isoformat()
    current_days = client_data.get("client_locker_days_remaining", 0)

    client_ref.update({
        "locker_number":               payload.locker_number,
        "client_locker_days_remaining": current_days + rental_days,
    })

    db.collection("locker_rentals").add({
        "client_name":       payload.client_name,
        "locker_number":     payload.locker_number,
        "rented_at":         today.isoformat(),
        "expires_at":        expires,
        "days_added":        rental_days,
        "assigned_by_admin": True,
    })

    _write_sale_log(payload.client_name, price)

    return {
        "client_name":                payload.client_name,
        "locker_number":              payload.locker_number,
        "days_added":                 rental_days,
        "expires_at":                 expires,
        "client_locker_days_remaining": current_days + rental_days,
    }


# ── Rental history ────────────────────────────────────────────

@router.get("/rentals")
def list_rentals(_: TokenData = Depends(require_admin)):
    return [d.to_dict() for d in
            db.collection("locker_rentals").stream()]


@router.get("/rentals/{client_name}")
def get_client_rentals(client_name: str,
                       _: TokenData = Depends(require_any)):
    return [d.to_dict() for d in
            db.collection("locker_rentals")
              .where("client_name", "==", client_name)
              .order_by("rented_at", direction="DESCENDING")
              .stream()]
