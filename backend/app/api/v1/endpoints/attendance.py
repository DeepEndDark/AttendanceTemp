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

    Firestore-level date filters are applied where possible to reduce
    documents streamed. Client-side filters remain as a safety net for
    legacy docs where log_date may need path-derivation.
    """
    query = db.collection_group("logs")
    if client_name:
        query = query.where("client_name", "==", client_name)

    # Push date filters to Firestore to avoid full collection scan
    if date_exact:
        query = query.where("log_date", "==", date_exact)
    elif date_from and date_to:
        query = query.where("log_date", ">=", date_from) \
                     .where("log_date", "<=", date_to)
    elif date_from:
        query = query.where("log_date", ">=", date_from)
    elif date_to:
        query = query.where("log_date", "<=", date_to)

    results = []
    for doc in query.stream():
        d = doc.to_dict()
        # Derive log_date from path as fallback: attendance_logs/{date}/logs/{uid}
        parts = doc.reference.path.split("/")
        d["log_date"] = parts[1] if (
            len(parts) >= 4 and parts[0] == "attendance_logs"
        ) else d.get("log_date", "")

        # Client-side safety filters for legacy docs
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


# ── View logs (any role) — delete stays admin-only, see below ─

@router.get("/", response_model=list[AttendanceLogRead])
def list_all_attendance(
    client_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    date_exact: str | None = None,
    _: TokenData = Depends(require_any),
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
    ref.update({
        "client_status":          False,
        "client_current_uid_log": None,
    })

    parts = log_ref.path.split("/")
    log_data["log_date"] = parts[1] if len(parts) >= 4 else ""
    log_data["time_out"] = now_str
    return _to_read(log_data)


# ── Fingerprint continuous scan ───────────────────────────────

@router.delete("/{log_uid}", response_model=dict)
def delete_attendance_log(log_uid: int, _: TokenData = Depends(require_admin)):
    """
    Admin only. Permanently deletes an attendance log by UID.
    If the client is currently timed-in on this log, their status is reset to timed-out.
    """
    results = list(
        db.collection_group("logs").where("log_uid", "==", log_uid).stream()
    )
    if not results:
        raise HTTPException(status_code=404, detail="Attendance log not found")

    log_ref  = results[0].reference
    log_data = results[0].to_dict()
    client_name = log_data.get("client_name")

    # If client is currently timed-in on this exact log, reset their status
    if client_name:
        client_ref  = clients().document(client_name)
        client_doc  = client_ref.get()
        if client_doc.exists:
            cd = client_doc.to_dict()
            if cd.get("client_current_uid_log") == log_uid and cd.get("client_status"):
                client_ref.update({
                    "client_status": False,
                    "client_current_uid_log": None,
                })

    log_ref.delete()
    return {"deleted": True, "log_uid": log_uid}


@router.post("/finger-touch")
def finger_touch(_: TokenData = Depends(require_any)):
    """
    Blocks silently until a finger is physically placed on the scanner
    (up to 30 s), then returns. Client display stays on idle screen
    while this is waiting. Returns {"touched": true} or {"touched": false}
    on timeout (no finger placed within 30 s — loop retries).
    """
    import logging as _log
    _log = _log.getLogger(__name__)
    from app.core import fingerprint as fp

    _log.info("FINGER-TOUCH: waiting for finger placement...")
    if not fp.SCANNER_AVAILABLE:
        _log.warning("FINGER-TOUCH: scanner unavailable")
        return {"touched": False, "scanner_available": False}

    touched = fp.wait_for_touch(timeout=30.0)
    if touched:
        _log.info("FINGER-TOUCH: finger detected")
    else:
        _log.info("FINGER-TOUCH: timeout — no finger in 30 s")
    return {"touched": touched, "scanner_available": True}

@router.post("/scan")
def fingerprint_scan(_: TokenData = Depends(require_any)):
    """
    Reads the next FID from the always-armed scanner queue, identifies,
    then auto-executes time-in or time-out. Returns a display event dict.
    """
    import logging as _log
    _log = _log.getLogger(__name__)
    from app.core import fingerprint as fp

    _log.info("SCAN: identifying finger...")
    if not fp.SCANNER_AVAILABLE:
        _log.warning("SCAN: scanner unavailable")
        return {"type": "scanner_error", "title": "Scanner Unavailable",
                "subtitle": "Manual mode only"}

    if not fp._cache:
        _log.warning("SCAN: no enrolled clients in cache")
        return {"type": "no_match", "title": "No Enrolled Clients",
                "subtitle": "Enroll clients before using fingerprint scan"}

    client_name = fp.identify_from_cache(rearm=False)
    _log.info(f"SCAN: result → {client_name!r}")

    if client_name is None:
        return {"type": "no_match", "title": "No Match Found",
                "subtitle": "Please try again or see staff"}

    ref = clients().document(client_name)
    doc = ref.get()
    if not doc.exists:
        return {"type": "no_match", "title": "Not Found",
                "subtitle": client_name}

    data      = doc.to_dict()
    days_left = data.get("client_days_remaining", 0)

    if days_left <= 0:
        return {"type": "expired", "title": client_name,
                "subtitle": "Subscription expired — please renew"}

    currently_in = data.get("client_status", False)
    now          = datetime.now()
    today        = date.today().isoformat()

    if not currently_in:
        uid = next_attendance_uid()
        log_doc = {
            "log_uid": uid, "log_date": today,
            "client_name": client_name,
            "time_in": now.strftime("%H:%M:%S"), "time_out": None,
        }
        db.collection("attendance_logs").document(today).set(
            {"_date": today}, merge=True)
        db.collection("attendance_logs").document(today) \
          .collection("logs").document(str(uid)).set(log_doc)
        ref.update({"client_status": True, "client_current_uid_log": uid})

        if days_left <= 2:
            return {"type": "expiry_warn", "title": client_name,
                    "subtitle": f"Timed in at {log_doc['time_in']}  |  "
                                f"{days_left} day(s) remaining"}
        return {"type": "time_in", "title": client_name,
                "subtitle": f"Timed in at {log_doc['time_in']}"}
    else:
        uid     = data.get("client_current_uid_log")
        now_str = now.strftime("%H:%M:%S")
        results = list(
            db.collection_group("logs").where("log_uid", "==", uid).stream())
        if results:
            results[0].reference.update({"time_out": now_str})
        ref.update({
            "client_status":          False,
            "client_current_uid_log": None,
        })
        return {"type": "time_out", "title": client_name,
                "subtitle": f"Timed out at {now_str}"}