from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import items
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate
from app.schemas.token import TokenData

router = APIRouter(prefix="/items", tags=["items"])


def _to_read(d: dict) -> ItemRead:
    stock = d.get("stock", 0)
    reserved = d.get("reserved_stock", 0)
    return ItemRead(
        item_name=d["item_name"],
        price=d["price"],
        stock=stock,
        reserved_stock=reserved,
        available_stock=max(0, stock - reserved),
    )


@router.get("/", response_model=list[ItemRead])
def list_items(_: TokenData = Depends(require_any)):
    return [_to_read(d.to_dict()) for d in items().stream()]


@router.get("/{item_name}", response_model=ItemRead)
def get_item(item_name: str, _: TokenData = Depends(require_any)):
    doc = items().document(item_name).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Item not found")
    return _to_read(doc.to_dict())


@router.post("/", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, _: TokenData = Depends(require_admin)):
    ref = items().document(payload.item_name)
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Item already exists")
    data = {"item_name": payload.item_name, "price": payload.price,
            "stock": payload.stock, "reserved_stock": 0}
    ref.set(data)
    return _to_read(data)


@router.patch("/{item_name}", response_model=ItemRead)
def update_item(item_name: str, payload: ItemUpdate,
                _: TokenData = Depends(require_admin)):
    ref = items().document(item_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Item not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    ref.update(updates)
    return _to_read(ref.get().to_dict())


@router.delete("/{item_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_name: str, _: TokenData = Depends(require_admin)):
    ref = items().document(item_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Item not found")
    ref.delete()
