from datetime import date, datetime
from pydantic import BaseModel


class ReportItemRead(BaseModel):
    item_name: str
    total_qty_sold: int
    total_value: float

    model_config = {"from_attributes": True}


class ReportRead(BaseModel):
    report_date: str
    total_revenue: float
    generated_at: str
    items: list[ReportItemRead]

    model_config = {"from_attributes": True}
