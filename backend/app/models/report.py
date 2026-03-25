from datetime import date, datetime

from sqlalchemy import Integer, Float, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ReportItem(Base):
    __tablename__ = "report_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, ForeignKey("daily_reports.report_date"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(150), nullable=False)
    total_qty_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)

    report: Mapped["DailyReport"] = relationship("DailyReport", back_populates="items")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_revenue: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list[ReportItem]] = relationship(
        "ReportItem", back_populates="report", cascade="all, delete-orphan"
    )
