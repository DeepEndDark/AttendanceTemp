from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_any
from app.core.database import get_db
from app.models.item import Item
from app.models.client import Client
from app.models.sales import SaleItem, SaleLog
from app.schemas.sales import SaleItemAdd, SaleItemSchema, SaleOpen, SaleRead
from app.schemas.token import TokenData

router = APIRouter(prefix="/sales", tags=["sales"])


def _to_read(sale: SaleLog) -> SaleRead:
    return SaleRead(
        sales_uid=sale.sales_uid,
        sale_date=sale.sale_date.isoformat(),
        client_name=sale.client_name,
        sale_status=sale.sale_status,
        item_list=[
            SaleItemSchema(
                item_name=si.item_name,
                item_qty=si.item_qty,
                item_total_price=si.item_total_price,
            )
            for si in sale.item_list
        ],
        total_price=sale.total_price,
    )


# ── Both roles ────────────────────────────────────────────────

@router.get("/open", response_model=list[SaleRead])
def list_open_sales(_: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    """All open sales — sales users see this; it filters to active clients at the frontend."""
    sales = db.query(SaleLog).filter(SaleLog.sale_status == "open").order_by(
        SaleLog.sale_date.desc(), SaleLog.sales_uid.desc()
    ).all()
    return [_to_read(s) for s in sales]


@router.post("/open", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
def open_sale(payload: SaleOpen, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    """
    Open a new sale for a client. If the client already has an open sale today,
    return that existing sale instead of creating a duplicate.
    """
    today = datetime.now().date()
    existing = db.query(SaleLog).filter(
        SaleLog.client_name == payload.client_name,
        SaleLog.sale_date == today,
        SaleLog.sale_status == "open",
    ).first()
    if existing:
        return _to_read(existing)

    sale = SaleLog(
        sale_date=today,
        client_name=payload.client_name,
        sale_status="open",
        total_price=0.0,
    )
    db.add(sale)
    db.flush()

    # Write pointer onto client record
    client = db.query(Client).filter(Client.client_name == payload.client_name).first()
    if client:
        client.client_current_sale_uid = sale.sales_uid

    db.commit()
    db.refresh(sale)
    return _to_read(sale)


@router.post("/{uid}/add-item", response_model=SaleRead)
def add_item_to_sale(
    uid: int,
    payload: SaleItemAdd,
    _: TokenData = Depends(require_any),
    db: Session = Depends(get_db),
):
    """Add an item to an open sale, reserving the stock immediately."""
    sale = db.query(SaleLog).filter(SaleLog.sales_uid == uid).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.sale_status != "open":
        raise HTTPException(status_code=400, detail="Cannot add items to a closed sale")

    item = db.query(Item).filter(Item.item_name == payload.item_name).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item '{payload.item_name}' not found")
    if item.available_stock < payload.item_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient available stock for '{payload.item_name}' "
                   f"(available: {item.available_stock})",
        )

    # Reserve stock
    item.reserved_stock += payload.item_qty

    # Check if item already exists in this sale — update qty if so
    existing_si = next((si for si in sale.item_list if si.item_name == payload.item_name), None)
    subtotal = round(item.price * payload.item_qty, 2)
    if existing_si:
        existing_si.item_qty += payload.item_qty
        existing_si.item_total_price = round(existing_si.item_total_price + subtotal, 2)
    else:
        db.add(SaleItem(
            sales_uid=uid,
            item_name=payload.item_name,
            item_qty=payload.item_qty,
            item_total_price=subtotal,
        ))

    sale.total_price = round(sum(
        (si.item_total_price for si in sale.item_list), subtotal if not existing_si else 0.0
    ), 2)
    # Recalculate total cleanly
    db.flush()
    db.refresh(sale)
    sale.total_price = round(sum(si.item_total_price for si in sale.item_list), 2)
    db.commit()
    db.refresh(sale)
    return _to_read(sale)


@router.delete("/{uid}/remove-item/{item_name}", response_model=SaleRead)
def remove_item_from_sale(
    uid: int,
    item_name: str,
    _: TokenData = Depends(require_any),
    db: Session = Depends(get_db),
):
    """Remove an item from an open sale, releasing its reserved stock."""
    sale = db.query(SaleLog).filter(SaleLog.sales_uid == uid).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.sale_status != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")

    sale_item = next((si for si in sale.item_list if si.item_name == item_name), None)
    if not sale_item:
        raise HTTPException(status_code=404, detail="Item not in this sale")

    item = db.query(Item).filter(Item.item_name == item_name).first()
    if item:
        item.reserved_stock = max(0, item.reserved_stock - sale_item.item_qty)

    db.delete(sale_item)
    db.flush()
    db.refresh(sale)
    sale.total_price = round(sum(si.item_total_price for si in sale.item_list), 2)
    db.commit()
    db.refresh(sale)
    return _to_read(sale)


@router.post("/{uid}/close", response_model=SaleRead)
def close_sale(uid: int, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    """
    Close a sale: convert reserved stock to actual deduction, mark as closed.
    Stock is only permanently deducted at this point.
    """
    sale = db.query(SaleLog).filter(SaleLog.sales_uid == uid).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale.sale_status != "open":
        raise HTTPException(status_code=400, detail="Sale is already closed")
    if not sale.item_list:
        raise HTTPException(status_code=400, detail="Cannot close an empty sale")

    for si in sale.item_list:
        item = db.query(Item).filter(Item.item_name == si.item_name).first()
        if item:
            item.stock = max(0, item.stock - si.item_qty)
            item.reserved_stock = max(0, item.reserved_stock - si.item_qty)

    sale.sale_status = "closed"

    # Clear pointer on client record
    client = db.query(Client).filter(Client.client_name == sale.client_name).first()
    if client:
        client.client_current_sale_uid = 0

    db.commit()
    db.refresh(sale)
    return _to_read(sale)


# ── Admin-only: full history ──────────────────────────────────

@router.get("/", response_model=list[SaleRead])
def list_all_sales(_: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    sales = db.query(SaleLog).order_by(
        SaleLog.sale_date.desc(), SaleLog.sales_uid.desc()
    ).all()
    return [_to_read(s) for s in sales]


@router.get("/date/{date_str}", response_model=list[SaleRead])
def get_sales_by_date(
    date_str: str,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    sales = db.query(SaleLog).filter(SaleLog.sale_date == d).all()
    return [_to_read(s) for s in sales]