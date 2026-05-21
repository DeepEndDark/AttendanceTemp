from pydantic import BaseModel

class SaleItemSchema(BaseModel):
    item_name: str
    item_qty: int
    item_total_price: float

class SaleItemAdd(BaseModel):
    item_name: str
    item_qty: int

class SaleOpen(BaseModel):
    client_name: str

class SaleRead(BaseModel):
    sales_uid: int
    sale_date: str
    client_name: str
    sale_status: str
    item_list: list[SaleItemSchema]
    total_price: float
