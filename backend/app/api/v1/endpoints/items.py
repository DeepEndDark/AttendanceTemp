from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_any
from app.core.database import get_db
from app.models.item import Item
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/items", tags=["items"])


def _to_read(item: Item) -> ItemRead:
    return ItemRead(
        item_name=item.item_name,
        price=item.price,
        stock=item.stock,
        reserved_stock=item.reserved_stock,
        available_stock=item.available_stock,
    )


@router.get("/", response_model=list[ItemRead])
def list_items(_: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    return [_to_read(i) for i in db.query(Item).all()]


@router.get("/{item_name}", response_model=ItemRead)
def get_item(item_name: str, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.item_name == item_name).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _to_read(item)


@router.post("/", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, _: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(Item).filter(Item.item_name == payload.item_name).first():
        raise HTTPException(status_code=409, detail="Item already exists")
    item = Item(item_name=payload.item_name, price=payload.price, stock=payload.stock, reserved_stock=0)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_read(item)


@router.patch("/{item_name}", response_model=ItemRead)
def update_item(
    item_name: str,
    payload: ItemUpdate,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    item = db.query(Item).filter(Item.item_name == item_name).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if payload.price is not None:
        item.price = payload.price
    if payload.stock is not None:
        item.stock = payload.stock
    db.commit()
    db.refresh(item)
    return _to_read(item)


@router.delete("/{item_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_name: str, _: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.item_name == item_name).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
