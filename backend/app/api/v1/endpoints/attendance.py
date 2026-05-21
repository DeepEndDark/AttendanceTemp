from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import require_admin, require_any
from app.core.firestore_client import clients, db, next_attendance_uid
from app.schemas.attendance import AttendanceLogRead, TimeInRequest, TimeOutRequest
from app.schemas.token import TokenData

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _to_read(d: dict) -> AttendanceLogRead:
    return AttendanceLogRead(
        log_uid=d["log_uid"],
        log_date=d.get("log_date", ""),
        client_name=d["client_name"],
        time_in=d["time_in"],
        time_out=d.get("time_out"),
        expiry_warning=d.get("expiry_warning", False),
        days_remaining=d.get("days_remaining", 0),
    )


def _fetch_all_logs(
    client_name: str | None = None,
    date_exact: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    collection_group("logs") queries ALL logs subcollections at once,
    bypassing the phantom-document problem where date parent docs are
    invisible to .stream().
    """
    query = db.collection_group("logs")
    if client_name:
        query = query.where("client_name", "==", client_name)

    results = []
    for doc in query.stream():
        d = doc.to_dict()
        # Derive log_date from path: attendance_logs/{date}/logs/{uid}
        parts = doc.reference.path.split("/")
        d["log_date"] = parts[1] if (
            len(parts) >= 4 and parts[0] == "attendance_logs"
        ) else d.get("log_date", "")

        ld = d["log_date"]
        if date_exact and ld != date_exact:
            continue
        if date_from and ld < date_from:
            continue
        if date_to and ld > date_to:
            continue
        results.append(d)

    return sorted(
        results,
        key=lambda x: (x.get("log_date", ""), x.get("log_uid", 0)),
        reverse=True,
    )


# ── Admin: view logs ──────────────────────────────────────────

@router.get("/", response_model=list[AttendanceLogRead])
def list_all_attendance(
    client_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_exact: str | None = None,
    _: TokenData = Depends(require_admin),
):
    return [_to_read(l) for l in _fetch_all_logs(
        client_name=client_name,
        date_exact=date_exact,
        date_from=date_from,
        date_to=date_to,
    )]


@router.get("/client/{client_name}", response_model=list[AttendanceLogRead])
def get_logs_for_client(client_name: str,
                        _: TokenData = Depends(require_any)):
    return [_to_read(l) for l in _fetch_all_logs(client_name=client_name)]


# ── Both roles: time-in / time-out ───────────────────────────

@router.post("/time-in", response_model=AttendanceLogRead,
             status_code=status.HTTP_201_CREATED)
def time_in(payload: TimeInRequest, _: TokenData = Depends(require_any)):
    ref = clients().document(payload.client_name)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")
    data = doc.to_dict()

    if data.get("client_days_remaining", 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active subscription. Please renew before entering.")

    if data.get("client_status", False):
        raise HTTPException(status_code=400,
                            detail="Client is already timed in")

    now   = datetime.now()
    today = date.today().isoformat()
    uid   = next_attendance_uid()

    log_doc = {
        "log_uid":     uid,
        "log_date":    today,
        "client_name": payload.client_name,
        "time_in":     now.strftime("%H:%M:%S"),
        "time_out":    None,
    }

    # Touch parent date document so .stream() can find it
    db.collection("attendance_logs").document(today).set(
        {"_date": today}, merge=True)
    db.collection("attendance_logs").document(today) \
      .collection("logs").document(str(uid)).set(log_doc)

    days_left = data.get("client_days_remaining", 0)
    ref.update({
        "client_status":        True,
        "client_current_uid_log": uid,
    })

    log_doc["expiry_warning"] = days_left <= 2
    log_doc["days_remaining"] = days_left
    return _to_read(log_doc)


@router.post("/time-out", response_model=AttendanceLogRead)
def time_out(payload: TimeOutRequest, _: TokenData = Depends(require_any)):
    ref = clients().document(payload.client_name)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Client not found")
    data = doc.to_dict()

    if not data.get("client_status", False):
        raise HTTPException(status_code=400,
                            detail="Client is not timed in")

    uid = data["client_current_uid_log"]

    # Find the log via collection_group — avoids phantom doc issue
    results = list(
        db.collection_group("logs").where("log_uid", "==", uid).stream()
    )
    if not results:
        raise HTTPException(status_code=404,
                            detail="Attendance log not found")

    log_ref  = results[0].reference
    log_data = results[0].to_dict()
    now_str  = datetime.now().strftime("%H:%M:%S")

    log_ref.update({"time_out": now_str})
    ref.update({"client_status": False})

    parts = log_ref.path.split("/")
    log_data["log_date"] = parts[1] if len(parts) >= 4 else ""
    log_data["time_out"] = now_str
    return _to_read(log_data)
