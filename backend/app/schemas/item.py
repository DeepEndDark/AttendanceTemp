from pydantic import BaseModel


class ItemCreate(BaseModel):
    item_name: str
    price: float
    stock: int = 0


class ItemUpdate(BaseModel):
    price: float | None = None
    stock: int | None = None


class ItemRead(BaseModel):
    item_name: str
    price: float
    stock: int
    reserved_stock: int
    available_stock: int

    model_config = {"from_attributes": True}
