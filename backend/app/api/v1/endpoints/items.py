from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import items
from app.schemas.item import (
    ItemCreate, ItemRead, ItemUpdate, ItemCategoryUpdate,
)
from pydantic import BaseModel
from app.schemas.token import TokenData

class RenamePayload(BaseModel):
    new_name: str

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
        category=d.get("category") or None,
    )


@router.get("/", response_model=list[ItemRead])
def list_items(_: TokenData = Depends(require_any)):
    return [_to_read(d.to_dict()) for d in items().stream()]


@router.get("/categories", response_model=list[str])
def list_item_categories(_: TokenData = Depends(require_any)):
    """
    Sorted list of every category currently in use. An item's category
    is just an optional field on the item doc — there's no separate
    categories collection — so this is derived by scanning items rather
    than being its own source of truth. An item without a category is
    simply omitted here; items are never required to belong to one.
    """
    names = {
        d.to_dict().get("category")
        for d in items().stream()
        if d.to_dict().get("category")
    }
    return sorted(names)


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
            "stock": payload.stock, "reserved_stock": 0,
            "category": payload.category or None}
    ref.set(data)
    return _to_read(data)


@router.patch("/{item_name}", response_model=ItemRead)
def update_item(item_name: str, payload: ItemUpdate,
                _: TokenData = Depends(require_admin)):
    ref = items().document(item_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Item not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        ref.update(updates)
    return _to_read(ref.get().to_dict())


@router.post("/{item_name}/category", response_model=ItemRead)
def set_item_category(item_name: str, payload: ItemCategoryUpdate,
                      _: TokenData = Depends(require_admin)):
    """
    Sets, moves, or clears an item's category — separate from the general
    update_item PATCH because that endpoint's None-means-"unchanged"
    convention can't express "remove this item from its category".
    An empty/None category is valid: items don't have to belong to one,
    and can switch freely between having one and not.
    """
    ref = items().document(item_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Item not found")
    ref.update({"category": payload.category or None})
    return _to_read(ref.get().to_dict())


@router.delete("/{item_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_name: str, _: TokenData = Depends(require_admin)):
    ref = items().document(item_name)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Item not found")
    ref.delete()


@router.post("/{item_name}/rename")
def rename_item(item_name: str,
                payload: RenamePayload,
                _: TokenData = Depends(require_admin)):
    """
    Rename an item. Creates new doc, copies data, deletes old.
    Updates open sale line items to the new name so close_sale
    stock deduction still works correctly.
    Closed sales preserve original names by design.
    """
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name required")
    if new_name == item_name:
        raise HTTPException(status_code=400, detail="New name is same as current")

    old_ref = items().document(item_name)
    old_doc = old_ref.get()
    if not old_doc.exists:
        raise HTTPException(status_code=404, detail="Item not found")

    new_ref = items().document(new_name)
    if new_ref.get().exists:
        raise HTTPException(status_code=409, detail="Name already taken")

    from app.core.firestore_client import db
    data = old_doc.to_dict()
    data["item_name"] = new_name
    new_ref.set(data)
    old_ref.delete()

    # Update open sale line items referencing the old name so that
    # close_sale stock deduction still resolves the correct item doc.
    open_sales = list(
        db.collection_group("sales")
          .where("sale_status", "==", "open")
          .stream()
    )
    batch = db.batch()
    batch_count = 0
    for sale_doc in open_sales:
        for item_doc in sale_doc.reference.collection("items") \
                                          .where("item_name", "==", item_name) \
                                          .stream():
            batch.update(item_doc.reference, {"item_name": new_name})
            batch_count += 1
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
    if batch_count:
        batch.commit()

    return {"renamed": item_name, "new_name": new_name}