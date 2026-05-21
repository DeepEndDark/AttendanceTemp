from pydantic import BaseModel

class ReportLineItem(BaseModel):
    name: str
    qty: int
    cost: float
    is_subscription: bool = False

class ClientPurchaseRead(BaseModel):
    client_name: str
    lines: list[ReportLineItem]
    client_total: float

class ReportRead(BaseModel):
    report_date: str
    total_revenue: float
    generated_at: str
    purchases: list[ClientPurchaseRead]

class MonthlyReportRead(BaseModel):
    year: int
    month: int
    total_revenue: float
    generated_at: str
    purchases: list[ClientPurchaseRead]
