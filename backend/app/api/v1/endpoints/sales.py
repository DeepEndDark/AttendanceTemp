from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import db, clients, items, next_sales_uid
from app.schemas.sales import SaleItemAdd, SaleItemSchema, SaleOpen, SaleRead
from app.schemas.token import TokenData

router = APIRouter(prefix="/sales", tags=["sales"])


def _touch_sale_date(date_str: str):
    """Ensure parent date doc exists so .stream() finds subcollections."""
    db.collection("sale_logs").document(date_str).set(
        {"_date": date_str}, merge=True)


def _fetch_sale_by_uid(uid: int):
    """Find a sale via collection_group. Returns (data, ref) or (None, None)."""
    results = list(
        db.collection_group("sales")
          .where("sales_uid", "==", uid)
          .stream()
    )
    if not results:
        return None, None
    doc  = results[0]
    data = doc.to_dict()
    # Derive sale_date from path: sale_logs/{date}/sales/{uid}
    parts = doc.reference.path.split("/")
    data["sale_date"] = parts[1] if len(parts) >= 4 else data.get("sale_date", "")
    data["item_list"] = [i.to_dict() for i in
                         doc.reference.collection("items").stream()]
    return data, doc.reference


def _collect_sales(
    client_name: str | None = None,
    item_name_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_exact: str | None = None,
    status_filter: str | None = None,
) -> list[dict]:
    """
    collection_group("sales") reads across all date partitions,
    bypassing phantom-document problem.
    """
    query = db.collection_group("sales")
    if client_name:
        query = query.where("client_name", "==", client_name)
    if status_filter and status_filter != "all":
        query = query.where("sale_status", "==", status_filter)

    results = []
    for doc in query.stream():
        # Guard: only sale_logs subcollections
        if not doc.reference.path.startswith("sale_logs/"):
            continue
        data   = doc.to_dict()
        parts  = doc.reference.path.split("/")
        d_str  = parts[1] if len(parts) >= 4 else data.get("sale_date", "")

        if date_exact and d_str != date_exact:
            continue
        if date_from and d_str < date_from:
            continue
        if date_to and d_str > date_to:
            continue

        data["sale_date"] = d_str
        item_list = [i.to_dict() for i in
                     doc.reference.collection("items").stream()]

        if item_name_filter:
            f = item_name_filter.lower()
            if not any(f in i.get("item_name", "").lower()
                       for i in item_list):
                continue

        data["item_list"] = item_list
        results.append(data)

    return sorted(results,
                  key=lambda x: (x.get("sale_date", ""),
                                 x.get("sales_uid", 0)),
                  reverse=True)


def _to_read(data: dict) -> SaleRead:
    return SaleRead(
        sales_uid=data["sales_uid"],
        sale_date=data.get("sale_date", ""),
        client_name=data["client_name"],
        sale_status=data["sale_status"],
        item_list=[SaleItemSchema(**i) for i in data.get("item_list", [])],
        total_price=data.get("total_price", 0.0),
    )


# ── Both roles ────────────────────────────────────────────────

@router.get("/open", response_model=list[SaleRead])
def list_open_sales(_: TokenData = Depends(require_any)):
    return [_to_read(s) for s in _collect_sales(status_filter="open")]


@router.post("/open", response_model=SaleRead,
             status_code=status.HTTP_201_CREATED)
def open_sale(payload: SaleOpen, _: TokenData = Depends(require_any)):
    today    = date.today().isoformat()
    existing = _collect_sales(client_name=payload.client_name,
                               date_exact=today, status_filter="open")
    if existing:
        return _to_read(existing[0])

    uid       = next_sales_uid()
    sale_data = {
        "sales_uid":    uid,
        "client_name":  payload.client_name,
        "sale_status":  "open",
        "total_price":  0.0,
        "sale_date":    today,
    }
    _touch_sale_date(today)
    db.collection("sale_logs").document(today) \
      .collection("sales").document(str(uid)).set(sale_data)
    clients().document(payload.client_name).update(
        {"client_current_sale_uid": uid})
    sale_data["item_list"] = []
    return _to_read(sale_data)


@router.post("/{uid}/add-item", response_model=SaleRead)
def add_item(uid: int, payload: SaleItemAdd,
             _: TokenData = Depends(require_any)):
    sale_data, sale_ref = _fetch_sale_by_uid(uid)
    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    item_ref = items().document(payload.item_name)
    item_doc = item_ref.get()
    if not item_doc.exists:
        raise HTTPException(status_code=404,
                            detail=f"Item '{payload.item_name}' not found")
    item_data = item_doc.to_dict()
    available = item_data["stock"] - item_data.get("reserved_stock", 0)
    if available < payload.item_qty:
        raise HTTPException(status_code=400,
                            detail=f"Insufficient stock (available: {available})")

    subtotal = round(item_data["price"] * payload.item_qty, 2)
    item_ref.update({
        "reserved_stock": item_data.get("reserved_stock", 0) + payload.item_qty
    })

    items_col     = sale_ref.collection("items")
    existing_item = next((i for i in sale_data.get("item_list", [])
                          if i["item_name"] == payload.item_name), None)
    if existing_item:
        for idoc in items_col.where(
                "item_name", "==", payload.item_name).stream():
            idoc.reference.update({
                "item_qty":         existing_item["item_qty"] + payload.item_qty,
                "item_total_price": round(
                    existing_item["item_total_price"] + subtotal, 2),
            })
    else:
        items_col.add({
            "item_name":        payload.item_name,
            "item_qty":         payload.item_qty,
            "item_total_price": subtotal,
            "is_subscription":  False,
            "is_locker":        False,
        })

    new_total = round(sum(
        i.to_dict().get("item_total_price", 0)
        for i in items_col.stream()), 2)
    sale_ref.update({"total_price": new_total})

    updated, _ = _fetch_sale_by_uid(uid)
    return _to_read(updated)


@router.delete("/{uid}/remove-item/{item_name}", response_model=SaleRead)
def remove_item(uid: int, item_name: str,
                _: TokenData = Depends(require_any)):
    sale_data, sale_ref = _fetch_sale_by_uid(uid)
    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    items_col = sale_ref.collection("items")
    for idoc in items_col.where("item_name", "==", item_name).stream():
        qty      = idoc.to_dict().get("item_qty", 0)
        item_ref = items().document(item_name)
        if item_ref.get().exists:
            cur = item_ref.get().to_dict().get("reserved_stock", 0)
            item_ref.update({"reserved_stock": max(0, cur - qty)})
        idoc.reference.delete()

    new_total = round(sum(
        i.to_dict().get("item_total_price", 0)
        for i in items_col.stream()), 2)
    sale_ref.update({"total_price": new_total})

    updated, _ = _fetch_sale_by_uid(uid)
    return _to_read(updated)


@router.post("/{uid}/close", response_model=SaleRead)
def close_sale(uid: int, _: TokenData = Depends(require_any)):
    sale_data, sale_ref = _fetch_sale_by_uid(uid)
    if not sale_data:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale_data["sale_status"] != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")
    if not sale_data.get("item_list"):
        raise HTTPException(status_code=400,
                            detail="Cannot close an empty sale")

    for si in sale_data["item_list"]:
        if si.get("is_subscription") or si.get("is_locker"):
            continue
        item_ref = items().document(si["item_name"])
        if item_ref.get().exists:
            d = item_ref.get().to_dict()
            item_ref.update({
                "stock":         max(0, d["stock"] - si["item_qty"]),
                "reserved_stock": max(
                    0, d.get("reserved_stock", 0) - si["item_qty"]),
            })

    sale_ref.update({"sale_status": "closed"})
    clients().document(sale_data["client_name"]).update(
        {"client_current_sale_uid": 0})

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
    return [_to_read(s) for s in _collect_sales(
        client_name=client_name,
        item_name_filter=item_name,
        date_from=date_from,
        date_to=date_to,
        date_exact=date_exact,
        status_filter=sale_status,
    )]


@router.get("/client/{client_name}", response_model=list[SaleRead])
def get_sales_for_client(client_name: str,
                         _: TokenData = Depends(require_any)):
    return [_to_read(s) for s in _collect_sales(client_name=client_name)]
