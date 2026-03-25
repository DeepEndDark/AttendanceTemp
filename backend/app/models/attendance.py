from datetime import date, time

from sqlalchemy import Integer, String, Date, Time, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AttendanceLog(Base):
    __tablename__ = "attendance_logs"

    log_uid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(150), ForeignKey("client_list.client_name"), nullable=False)
    time_in: Mapped[time] = mapped_column(Time, nullable=False)
    time_out: Mapped[time | None] = mapped_column(Time, nullable=True)
