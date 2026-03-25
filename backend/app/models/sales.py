from datetime import date

from sqlalchemy import Integer, Float, String, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_uid: Mapped[int] = mapped_column(Integer, ForeignKey("sale_logs.sales_uid"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(150), nullable=False)
    item_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    item_total_price: Mapped[float] = mapped_column(Float, nullable=False)

    sale: Mapped["SaleLog"] = relationship("SaleLog", back_populates="item_list")


class SaleLog(Base):
    __tablename__ = "sale_logs"

    sales_uid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(150), ForeignKey("client_list.client_name"), nullable=False)
    sale_status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    total_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    item_list: Mapped[list[SaleItem]] = relationship(
        "SaleItem", back_populates="sale", cascade="all, delete-orphan"
    )
