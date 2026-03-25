from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Item(Base):
    __tablename__ = "item_catalogue"

    item_name: Mapped[str] = mapped_column(String(150), primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @property
    def available_stock(self) -> int:
        return max(0, self.stock - self.reserved_stock)
