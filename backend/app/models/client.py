from datetime import datetime

from sqlalchemy import String, Boolean, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Client(Base):
    __tablename__ = "client_list"

    client_name: Mapped[str] = mapped_column(String(150), primary_key=True)
    client_duration: Mapped[str] = mapped_column(String(100), nullable=False)
    client_status: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_current_uid_log: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_current_sale_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)