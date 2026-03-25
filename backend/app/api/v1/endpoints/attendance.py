from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_any
from app.core.database import get_db
from app.models.attendance import AttendanceLog
from app.models.client import Client
from app.schemas.attendance import AttendanceLogRead, TimeInRequest, TimeOutRequest
from app.schemas.token import TokenData

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _fmt_time(t: time | None) -> str | None:
    return t.strftime("%H:%M:%S") if t else None


def _to_read(log: AttendanceLog) -> AttendanceLogRead:
    return AttendanceLogRead(
        log_uid=log.log_uid,
        log_date=log.log_date.isoformat(),
        client_name=log.client_name,
        time_in=_fmt_time(log.time_in),
        time_out=_fmt_time(log.time_out),
    )


# ── Admin-only: view logs ─────────────────────────────────────

@router.get("/", response_model=list[AttendanceLogRead])
def list_all_attendance(_: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    logs = db.query(AttendanceLog).order_by(
        AttendanceLog.log_date.desc(), AttendanceLog.log_uid.desc()
    ).all()
    return [_to_read(l) for l in logs]


@router.get("/date/{date_str}", response_model=list[AttendanceLogRead])
def get_attendance_by_date(
    date_str: str,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    logs = db.query(AttendanceLog).filter(AttendanceLog.log_date == d).all()
    return [_to_read(l) for l in logs]


# ── Both roles: time-in / time-out ───────────────────────────

@router.post("/time-in", response_model=AttendanceLogRead, status_code=status.HTTP_201_CREATED)
def time_in(payload: TimeInRequest, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.client_name == payload.client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.client_status:
        raise HTTPException(status_code=400, detail="Client is already timed in")

    now = datetime.now()
    log = AttendanceLog(
        log_date=now.date(),
        client_name=payload.client_name,
        time_in=now.time().replace(microsecond=0),
        time_out=None,
    )
    db.add(log)
    db.flush()

    client.client_status = True
    client.client_current_uid_log = log.log_uid
    db.commit()
    db.refresh(log)
    return _to_read(log)


@router.post("/time-out", response_model=AttendanceLogRead)
def time_out(payload: TimeOutRequest, _: TokenData = Depends(require_any), db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.client_name == payload.client_name).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.client_status:
        raise HTTPException(status_code=400, detail="Client is not timed in")

    log = db.query(AttendanceLog).filter(
        AttendanceLog.log_uid == client.client_current_uid_log
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Attendance log entry not found")

    log.time_out = datetime.now().time().replace(microsecond=0)
    client.client_status = False
    db.commit()
    db.refresh(log)
    return _to_read(log)
