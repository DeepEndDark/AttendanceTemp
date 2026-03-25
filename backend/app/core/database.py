from collections.abc import Generator
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models.base import Base
    import app.models.account
    import app.models.client
    import app.models.attendance
    import app.models.item
    import app.models.sales
    import app.models.report

    Base.metadata.create_all(bind=engine)
    _seed()
    _auto_generate_yesterday_report()


def _seed() -> None:
    from app.models.account import Account
    from app.core.security import hash_password

    db = SessionLocal()
    try:
        if not db.query(Account).filter(Account.account_name == "admin").first():
            db.add(Account(
                account_name="admin",
                account_type="admin",
                hashed_password=hash_password("admin123"),
            ))
            db.commit()
    finally:
        db.close()


def _auto_generate_yesterday_report() -> None:
    """On startup, generate yesterday's report if it hasn't been created yet."""
    from app.models.report import DailyReport
    from app.core.report_generator import generate_daily_report

    yesterday = date.today() - timedelta(days=1)
    db = SessionLocal()
    try:
        existing = db.query(DailyReport).filter(DailyReport.report_date == yesterday).first()
        if not existing:
            generate_daily_report(db, yesterday)
    except Exception:
        pass
    finally:
        db.close()
