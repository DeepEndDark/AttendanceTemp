"""
Locker management.

Each client stores a `lockers` list:
    [{locker_number: int, days_remaining: int, expires_at: str}]

Multiple lockers per client are supported. Days stack per locker.
Daily tick decrements every locker independently and removes expired ones.

Legacy clients with flat locker_number / client_locker_days_remaining fields
are handled transparently in _doc_to_read (clients.py).
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import clients, db, next_sales_uid, system_state
from app.schemas.token import TokenData

router = APIRouter(prefix="/lockers", tags=["lockers"])
SETTINGS_DOC = "settings"


# ── Helpers ───────────────────────────────────────────────────

def _get_settings() -> dict:
    doc = system_state().document(SETTINGS_DOC).get()
    if doc.exists:
        return doc.to_dict()
    return {
        "total_lockers":            0,
        "locker_price":             0.0,
        "locker_rental_days":       30,
        "trainer_deduction_method": "fifo",
    }


def _all_rented_numbers() -> set[int]:
    """Set of all locker numbers currently assigned across all clients."""
    rented = set()
    for c in clients().stream():
        d = c.to_dict()
        for l in d.get("lockers", []):
            n = l.get("locker_number")
            if n:
                rented.add(n)
        # legacy field
        legacy = d.get("locker_number")
        if legacy:
            rented.add(legacy)
    return rented


def _lowest_available(total: int) -> int | None:
    rented = _all_rented_numbers()
    for i in range(1, total + 1):
        if i not in rented:
            return i
    return None


def _write_sale_log(client_name: str, locker_number: int, price: float):
    today = date.today().isoformat()
    uid   = next_sales_uid()
    db.collection("sale_logs").document(today).set({"_date": today}, merge=True)
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
        "item_name":        f"Locker #{locker_number} Rental",
        "item_qty":         1,
        "item_total_price": round(price, 2),
        "is_subscription":  False,
        "is_locker":        True,
    })


def _sync_legacy(lockers: list[dict]) -> dict:
    """Keep legacy flat fields in sync for any code still reading them."""
    if not lockers:
        return {
            "locker_number":               None,
            "client_locker_days_remaining": 0,
        }
    return {
        "locker_number":               lockers[0]["locker_number"],
        "client_locker_days_remaining": sum(
            l.get("days_remaining", 0) for l in lockers),
    }


# ── Schemas ───────────────────────────────────────────────────

class LockerSettings(BaseModel):
    total_lockers:            int | None   = None
    locker_price:             float | None = None
    locker_rental_days:       int | None   = None
    trainer_deduction_method: str | None   = None


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
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    ref.set(updates, merge=True)
    return ref.get().to_dict()


# ── Availability ──────────────────────────────────────────────

@router.get("/available", response_model=LockerAvailability)
def get_availability(_: TokenData = Depends(require_any)):
    s      = _get_settings()
    total  = s.get("total_lockers", 0)
    rented = len(_all_rented_numbers())
    return LockerAvailability(
        total=total,
        rented=min(rented, total),
        available=max(0, total - rented),
        price=s.get("locker_price", 0.0),
        rental_days=s.get("locker_rental_days", 30),
    )


# ── FIFO self-service rent ────────────────────────────────────

@router.post("/rent")
def rent_locker(payload: LockerRentRequest,
                _: TokenData = Depends(require_any)):
    """
    Auto-assigns the lowest available locker, or stacks days on the
    client's first existing locker if they already have one.
    """
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

    lockers: list[dict] = client_data.get("lockers", [])

    # Legacy migration: if client has flat fields but no lockers list
    if not lockers and client_data.get("locker_number"):
        lockers = [{
            "locker_number":  client_data["locker_number"],
            "days_remaining": client_data.get("client_locker_days_remaining", 0),
            "expires_at":     None,
        }]

    if lockers:
        # Stack days on first existing locker
        lockers[0]["days_remaining"] += rental_days
        lockers[0]["expires_at"]      = expires
        assigned = lockers[0]["locker_number"]
    else:
        assigned = _lowest_available(total)
        if assigned is None:
            raise HTTPException(status_code=400, detail="No lockers available")
        lockers.append({
            "locker_number":  assigned,
            "days_remaining": rental_days,
            "expires_at":     expires,
        })

    client_ref.update({
        "lockers": lockers,
        **_sync_legacy(lockers),
    })

    _write_sale_log(payload.client_name, assigned, price)

    return {
        "client_name":  payload.client_name,
        "locker_number": assigned,
        "days_added":   rental_days,
        "expires_at":   expires,
        "client_locker_days_remaining": sum(
            l["days_remaining"] for l in lockers),
    }


# ── Admin manual assign ───────────────────────────────────────

@router.post("/assign")
def assign_locker(payload: LockerAssignRequest,
                  _: TokenData = Depends(require_any)):
    """
    Assign a specific locker number to a client.
    - If client already has THIS locker → stacks days (additive).
    - If client already has a DIFFERENT locker → adds as second locker.
    - If locker is held by a different client → rejected.
    """
    s           = _get_settings()
    total       = s.get("total_lockers", 0)
    rental_days = s.get("locker_rental_days", 30)
    price       = s.get("locker_price", 0.0)

    if payload.locker_number < 1 or payload.locker_number > total:
        raise HTTPException(
            status_code=400,
            detail=f"Locker #{payload.locker_number} does not exist "
                   f"(total: {total})")

    client_ref = clients().document(payload.client_name)
    client_doc = client_ref.get()
    if not client_doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")
    client_data = client_doc.to_dict()

    # Check if locker is already taken by a different client
    for other in clients().stream():
        if other.id == payload.client_name:
            continue
        d = other.to_dict()
        for l in d.get("lockers", []):
            if l.get("locker_number") == payload.locker_number:
                raise HTTPException(
                    status_code=409,
                    detail=f"Locker #{payload.locker_number} is already "
                           f"assigned to '{other.id}'")
        # legacy field
        if d.get("locker_number") == payload.locker_number:
            raise HTTPException(
                status_code=409,
                detail=f"Locker #{payload.locker_number} is already "
                       f"assigned to '{other.id}'")

    today   = date.today()
    expires = (today + timedelta(days=rental_days - 1)).isoformat()

    lockers: list[dict] = client_data.get("lockers", [])

    # Legacy migration
    if not lockers and client_data.get("locker_number"):
        lockers = [{
            "locker_number":  client_data["locker_number"],
            "days_remaining": client_data.get("client_locker_days_remaining", 0),
            "expires_at":     None,
        }]

    # Check if client already has this specific locker → stack days
    existing = next(
        (l for l in lockers if l["locker_number"] == payload.locker_number),
        None)
    if existing:
        existing["days_remaining"] += rental_days
        existing["expires_at"]      = expires
    else:
        # New locker for this client
        lockers.append({
            "locker_number":  payload.locker_number,
            "days_remaining": rental_days,
            "expires_at":     expires,
        })

    client_ref.update({
        "lockers": lockers,
        **_sync_legacy(lockers),
    })

    _write_sale_log(payload.client_name, payload.locker_number, price)

    return {
        "client_name":   payload.client_name,
        "locker_number": payload.locker_number,
        "days_added":    rental_days,
        "expires_at":    expires,
        "client_locker_days_remaining": sum(
            l["days_remaining"] for l in lockers),
    }


# ── Rental history ────────────────────────────────────────────

@router.get("/rentals")
def list_rentals(_: TokenData = Depends(require_admin)):
    """All locker rental sale records across all clients."""
    results = []
    for sale_doc in db.collection_group("sales") \
                      .where("sale_status", "==", "closed").stream():
        for item in sale_doc.reference.collection("items") \
                            .where("is_locker", "==", True).stream():
            results.append({
                **sale_doc.to_dict(),
                "item": item.to_dict(),
            })
    return results


@router.get("/rentals/{client_name}")
def get_client_rentals(client_name: str,
                       _: TokenData = Depends(require_any)):
    """Locker rental sale records for a specific client."""
    results = []
    for sale_doc in db.collection_group("sales") \
                      .where("client_name", "==", client_name) \
                      .where("sale_status", "==", "closed").stream():
        for item in sale_doc.reference.collection("items") \
                            .where("is_locker", "==", True).stream():
            results.append({
                **sale_doc.to_dict(),
                "item": item.to_dict(),
            })
    return results


# ── Unassign specific locker (admin only) ─────────────────────

@router.delete("/unassign/{locker_number}", status_code=200)
def unassign_locker(locker_number: int,
                    _: TokenData = Depends(require_admin)):
    """
    Admin only. Removes a specific locker from whichever client holds it.
    Remaining days for that locker are forfeited.
    """
    owner_ref  = None
    owner_name = None
    owner_data = None

    for doc in clients().stream():
        d = doc.to_dict()
        # Check new lockers list
        for l in d.get("lockers", []):
            if l.get("locker_number") == locker_number:
                owner_ref  = doc.reference
                owner_name = d.get("client_name", doc.id)
                owner_data = d
                break
        # Check legacy field
        if not owner_ref and d.get("locker_number") == locker_number:
            owner_ref  = doc.reference
            owner_name = d.get("client_name", doc.id)
            owner_data = d
        if owner_ref:
            break

    if not owner_ref:
        raise HTTPException(status_code=404,
                            detail=f"Locker #{locker_number} is not assigned.")

    lockers = owner_data.get("lockers", [])
    if not lockers and owner_data.get("locker_number") == locker_number:
        # Legacy only
        lockers = []
    else:
        lockers = [l for l in lockers if l["locker_number"] != locker_number]

    owner_ref.update({
        "lockers": lockers,
        **_sync_legacy(lockers),
    })

    return {
        "unassigned":  locker_number,
        "client_name": owner_name,
        "lockers_remaining": len(lockers),
    }