from pydantic import BaseModel

class ItemCreate(BaseModel):
    item_name: str
    price: float
    stock: int = 0
    category: str | None = None

class ItemUpdate(BaseModel):
    price: float | None = None
    stock: int | None = None

class ItemCategoryUpdate(BaseModel):
    # Explicit endpoint (not folded into ItemUpdate) because ItemUpdate's
    # None-means-"don't change" convention can't represent "clear the
    # category back to uncategorized" — this one always sets it, treating
    # None/empty as "remove from category" rather than "leave unchanged".
    category: str | None = None

class ItemRead(BaseModel):
    item_name: str
    price: float
    stock: int
    reserved_stock: int
    available_stock: int
    category: str | None = None