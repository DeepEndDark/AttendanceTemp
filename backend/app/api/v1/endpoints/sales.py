from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import db, clients, items, next_sales_uid
from app.schemas.sales import SaleItemAdd, SaleItemSchema, SaleOpen, SaleRead
from app.schemas.token import TokenData

router = APIRouter(prefix="/sales", tags=["sales"])


def _touch_sale_date(date_str: str):
    """Ensure parent date doc exists so sale_logs/{date}/sales exists."""
    db.collection("sale_logs").document(date_str).set(
        {"_date": date_str},
        merge=True,
    )


def _sale_date_from_ref(doc_ref) -> str:
    """
    Extract sale date from:
        sale_logs/{date}/sales/{uid}
    """
    parts = doc_ref.path.split("/")

    if len(parts) >= 4 and parts[0] == "sale_logs":
        return parts[1]

    return ""


def _fetch_sale_header_by_uid(uid: int):
    """
    Find sale document by sales_uid without loading item subcollection.
    Returns (data, ref) or (None, None).

    Requires Firestore collection-group index:
        collection group: sales
        field: sales_uid ASC
    """
    results = list(
        db.collection_group("sales")
        .where("sales_uid", "==", uid)
        .limit(1)
        .stream()
    )

    if not results:
        return None, None

    doc = results[0]
    data = doc.to_dict()
    data["sale_date"] = data.get("sale_date") or _sale_date_from_ref(
        doc.reference
    )

    return data, doc.reference


def _fetch_sale_by_uid(uid: int):
    """
    Find sale document by sales_uid and include item_list.
    Returns (data, ref) or (None, None).

    This is used only for detail/mutation endpoints.
    Do not use this in the main list endpoint.
    """
    data, sale_ref = _fetch_sale_header_by_uid(uid)

    if not data:
        return None, None

    data["item_list"] = [
        i.to_dict()
        for i in sale_ref.collection("items").stream()
    ]

    return data, sale_ref


def _to_read(data: dict) -> SaleRead:
    return SaleRead(
        sales_uid=data["sales_uid"],
        sale_date=data.get("sale_date", ""),
        client_name=data["client_name"],
        sale_status=data["sale_status"],
        item_list=[
            SaleItemSchema(**i)
            for i in data.get("item_list", [])
        ],
        total_price=data.get("total_price", 0.0),
    )


def _to_header_read(data: dict) -> SaleRead:
    """
    Header-only SaleRead.

    Keeps response_model compatibility with the existing frontend/schema,
    but avoids loading item subcollections for the main table.
    """
    data = dict(data)
    data["item_list"] = []
    return _to_read(data)


def _release_reserved_items(sale_data: dict) -> None:
    """
    Release reserved stock for normal inventory items in an open sale.
    Does not touch subscription or locker lines.
    """
    for si in sale_data.get("item_list", []) or []:
        if si.get("is_subscription") or si.get("is_locker"):
            continue

        item_name = si.get("item_name")
        item_qty = si.get("item_qty", 0)

        if not item_name or item_qty <= 0:
            continue

        item_ref = items().document(item_name)
        item_doc = item_ref.get()

        if item_doc.exists:
            d = item_doc.to_dict()
            item_ref.update({
                "reserved_stock": max(
                    0,
                    d.get("reserved_stock", 0) - item_qty,
                )
            })


def _delete_sale_doc(
    uid: int,
    sale_data: dict,
    sale_ref,
    *,
    release_reserved: bool = True,
) -> dict:
    """
    Delete a sale log.

    If sale is open, reserved stock is released.
    If sale is closed, stock is NOT restored because it was already deducted
    when closed.
    """
    if release_reserved and sale_data.get("sale_status") == "open":
        _release_reserved_items(sale_data)

    client_name = sale_data.get("client_name")

    if client_name:
        client_ref = clients().document(client_name)
        client_doc = client_ref.get()

        if client_doc.exists:
            cdata = client_doc.to_dict()

            if cdata.get("client_current_sale_uid") == uid:
                client_ref.update({
                    "client_current_sale_uid": None
                })

    # Delete item subcollection docs in a batch.
    batch = db.batch()
    batch_count = 0
    for item_doc in sale_ref.collection("items").stream():
        batch.delete(item_doc.reference)
        batch_count += 1
        if batch_count >= 500:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count:
        batch.commit()

    # Delete sale doc.
    sale_ref.delete()

    # Optional cleanup: delete parent date doc if no sales remain.
    try:
        date_ref = sale_ref.parent.parent

        if date_ref is not None:
            remaining = list(
                date_ref.collection("sales").limit(1).stream()
            )

            if not remaining:
                date_ref.delete()

    except Exception:
        pass

    return {
        "deleted": True,
        "sales_uid": uid,
        "client_name": client_name,
    }


def _collect_sale_headers(
    client_name: str | None = None,
    item_name_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_exact: str | None = None,
    status_filter: str | None = None,
) -> list[dict]:
    """
    Fast sales list.

    Loads sale documents only, not item subcollections, unless item_name_filter
    is supplied. The normal Sales grid should call this without item filter.
    """
    query = db.collection_group("sales")

    if client_name:
        query = query.where("client_name", "==", client_name)

    if status_filter and status_filter != "all":
        query = query.where("sale_status", "==", status_filter)

    # Push date filters to Firestore to avoid full collection scan
    if date_exact:
        query = query.where("sale_date", "==", date_exact)
    elif date_from and date_to:
        query = query.where("sale_date", ">=", date_from) \
                     .where("sale_date", "<=", date_to)
    elif date_from:
        query = query.where("sale_date", ">=", date_from)
    elif date_to:
        query = query.where("sale_date", "<=", date_to)

    results = []

    for doc in query.stream():
        # Guard: only sale_logs/{date}/sales/{uid}
        if not doc.reference.path.startswith("sale_logs/"):
            continue

        data = doc.to_dict()
        d_str = data.get("sale_date") or _sale_date_from_ref(doc.reference)
        data["sale_date"] = d_str

        # Client-side safety filters for legacy docs
        if date_exact and d_str != date_exact:
            continue
        if date_from and d_str < date_from:
            continue
        if date_to and d_str > date_to:
            continue

        # Filtering by item requires reading that sale's item subcollection.
        # This is intentionally only done when the user actually filters by item.
        if item_name_filter:
            f = item_name_filter.lower()
            item_list = [
                i.to_dict()
                for i in doc.reference.collection("items").stream()
            ]

            if not any(
                f in i.get("item_name", "").lower()
                for i in item_list
            ):
                continue

        # Important: no item_list here for normal list response.
        data.pop("item_list", None)
        results.append(data)

    return sorted(
        results,
        key=lambda x: (
            x.get("sale_date", ""),
            x.get("sales_uid", 0),
        ),
        reverse=True,
    )


# ── Both roles ────────────────────────────────────────────────

@router.get("/open", response_model=list[SaleRead])
def list_open_sales(_: TokenData = Depends(require_any)):
    """
    Header-only open sales list.
    """
    return [
        _to_header_read(s)
        for s in _collect_sale_headers(status_filter="open")
    ]


@router.post(
    "/open",
    response_model=SaleRead,
    status_code=status.HTTP_201_CREATED,
)
def open_sale(payload: SaleOpen, _: TokenData = Depends(require_any)):
    today = date.today().isoformat()

    existing = _collect_sale_headers(
        client_name=payload.client_name,
        date_exact=today,
        status_filter="open",
    )

    if existing:
        existing_full, _ = _fetch_sale_by_uid(existing[0]["sales_uid"])
        return _to_read(existing_full)

    uid = next_sales_uid()

    sale_data = {
        "sales_uid": uid,
        "client_name": payload.client_name,
        "sale_status": "open",
        "total_price": 0.0,
        "sale_date": today,
    }

    _touch_sale_date(today)

    db.collection("sale_logs").document(today) \
        .collection("sales").document(str(uid)).set(sale_data)

    clients().document(payload.client_name).update({
        "client_current_sale_uid": uid
    })

    sale_data["item_list"] = []

    return _to_read(sale_data)


@router.get("/detail/{uid}", response_model=SaleRead)
def get_sale_detail(uid: int, _: TokenData = Depends(require_any)):
    """
    Full sale detail for row selection.
    Includes item_list.
    """
    sale_data, _ = _fetch_sale_by_uid(uid)

    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")

    return _to_read(sale_data)


@router.post("/{uid}/add-item", response_model=SaleRead)
def add_item(
    uid: int,
    payload: SaleItemAdd,
    _: TokenData = Depends(require_any),
):
    sale_data, sale_ref = _fetch_sale_by_uid(uid)

    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    item_ref = items().document(payload.item_name)
    item_doc = item_ref.get()

    if not item_doc.exists:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{payload.item_name}' not found",
        )

    item_data = item_doc.to_dict()
    available = item_data.get("stock", 0) - item_data.get(
        "reserved_stock", 0
    )

    if available < payload.item_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock (available: {available})",
        )

    subtotal = round(item_data["price"] * payload.item_qty, 2)

    item_ref.update({
        "reserved_stock": item_data.get("reserved_stock", 0)
                          + payload.item_qty
    })

    items_col = sale_ref.collection("items")

    existing_item = next(
        (
            i
            for i in sale_data.get("item_list", [])
            if i["item_name"] == payload.item_name
        ),
        None,
    )

    if existing_item:
        for idoc in items_col.where(
            "item_name",
            "==",
            payload.item_name,
        ).stream():
            idoc.reference.update({
                "item_qty": existing_item["item_qty"]
                            + payload.item_qty,
                "item_total_price": round(
                    existing_item["item_total_price"] + subtotal,
                    2,
                ),
            })

    else:
        items_col.add({
            "item_name": payload.item_name,
            "item_qty": payload.item_qty,
            "item_total_price": subtotal,
            "is_subscription": False,
            "is_locker": False,
        })

    new_total = round(
        sum(
            i.to_dict().get("item_total_price", 0)
            for i in items_col.stream()
        ),
        2,
    )

    sale_ref.update({
        "total_price": new_total
    })

    updated, _ = _fetch_sale_by_uid(uid)

    return _to_read(updated)


@router.delete("/{uid}/remove-item/{item_name}", response_model=SaleRead)
def remove_item(
    uid: int,
    item_name: str,
    _: TokenData = Depends(require_any),
):
    sale_data, sale_ref = _fetch_sale_by_uid(uid)

    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    items_col = sale_ref.collection("items")

    for idoc in items_col.where("item_name", "==", item_name).stream():
        qty = idoc.to_dict().get("item_qty", 0)

        item_ref = items().document(item_name)
        item_doc = item_ref.get()

        if item_doc.exists:
            cur = item_doc.to_dict().get("reserved_stock", 0)
            item_ref.update({
                "reserved_stock": max(0, cur - qty)
            })

        idoc.reference.delete()

    new_total = round(
        sum(
            i.to_dict().get("item_total_price", 0)
            for i in items_col.stream()
        ),
        2,
    )

    sale_ref.update({
        "total_price": new_total
    })

    updated, _ = _fetch_sale_by_uid(uid)

    return _to_read(updated)


@router.post("/{uid}/close")
def close_sale(uid: int, _: TokenData = Depends(require_any)):
    """
    Both sales and admin can close a sale.

    If the sale has no items, delete the open sale log instead of returning
    a 400 error.

    No response_model here because this can return either:
      - SaleRead-like dict for normal close
      - {"deleted": True, ...} for empty sale delete
    """
    sale_data, sale_ref = _fetch_sale_by_uid(uid)

    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")

    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    if not sale_data.get("item_list"):
        return _delete_sale_doc(
            uid,
            sale_data,
            sale_ref,
            release_reserved=True,
        )

    for si in sale_data["item_list"]:
        if si.get("is_subscription") or si.get("is_locker"):
            continue

        item_ref = items().document(si["item_name"])
        item_doc = item_ref.get()

        if item_doc.exists:
            d = item_doc.to_dict()
            item_ref.update({
                "stock": max(
                    0,
                    d.get("stock", 0) - si["item_qty"],
                ),
                "reserved_stock": max(
                    0,
                    d.get("reserved_stock", 0) - si["item_qty"],
                ),
            })

    sale_ref.update({
        "sale_status": "closed"
    })

    client_ref = clients().document(sale_data["client_name"])
    client_doc = client_ref.get()

    if client_doc.exists:
        client_ref.update({
            "client_current_sale_uid": None
        })

    updated, _ = _fetch_sale_by_uid(uid)

    return _to_read(updated)


# ── Admin only ────────────────────────────────────────────────

@router.get("/", response_model=list[SaleRead])
def list_all_sales(
    client_name: str | None = None,
    item_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_exact: str | None = None,
    sale_status: str | None = None,
    _: TokenData = Depends(require_admin),
):
    """
    Header-only sales list for the Sales grid.

    item_list is intentionally returned as [] to preserve SaleRead schema
    compatibility while avoiding N+1 Firestore subcollection reads.
    """
    return [
        _to_header_read(s)
        for s in _collect_sale_headers(
            client_name=client_name,
            item_name_filter=item_name,
            date_from=date_from,
            date_to=date_to,
            date_exact=date_exact,
            status_filter=sale_status,
        )
    ]


@router.delete("/{uid}", status_code=200)
def delete_sale(uid: int, _: TokenData = Depends(require_admin)):
    """
    Admin only.

    Deletes a sale log.

    If sale is open, reserved stock is released.
    If sale is closed, stock is NOT restored.
    """
    sale_data, sale_ref = _fetch_sale_by_uid(uid)

    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")

    return _delete_sale_doc(
        uid,
        sale_data,
        sale_ref,
        release_reserved=True,
    )


@router.get("/client/{client_name}", response_model=list[SaleRead])
def get_sales_for_client(
    client_name: str,
    _: TokenData = Depends(require_any),
):
    """
    Header-only client sales list.
    Use /sales/detail/{uid} for item_list.
    """
    return [
        _to_header_read(s)
        for s in _collect_sale_headers(client_name=client_name)
    ]