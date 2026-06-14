"""
Daily tick — runs on every app startup.
Subtracts one day from every active client subscription and locker.
Handles catch-up if the app was offline for multiple days.
"""
from datetime import date, timedelta
import logging

log = logging.getLogger(__name__)


def run_tick() -> None:
    from app.core.firestore_client import db, clients, system_state

    tick_ref = system_state().document("tick")
    tick_doc = tick_ref.get()
    today    = date.today()

    # Already ticked today — nothing to do
    if tick_doc.exists:
        try:
            last = date.fromisoformat(
                tick_doc.to_dict().get("last_tick_date", ""))
            if last >= today:
                return
        except (ValueError, TypeError):
            pass

    # Skip entirely on first run with empty database
    first_client = next(iter(clients().limit(1).stream()), None)
    if first_client is None:
        tick_ref.set({"last_tick_date": today.isoformat()}, merge=True)
        return

    try:
        last = date.fromisoformat(
            tick_doc.to_dict().get("last_tick_date", ""))             if tick_doc.exists else today - timedelta(days=1)
    except (ValueError, TypeError):
        last = today - timedelta(days=1)

    days_missed = (today - last).days
    if days_missed <= 0:
        return

    log.info(f"Daily tick: processing {days_missed} day(s) "
             f"({last} → {today})")

    for client_doc in clients().stream():
        _tick_client(client_doc.id, days_missed)

    tick_ref.set({"last_tick_date": today.isoformat()})
    log.info(f"Daily tick complete. last_tick_date={today.isoformat()}")



def auto_timeout_stale_sessions() -> None:
    """
    Find clients still marked as timed-in (client_status=True) whose last
    log entry is from a previous calendar day, and automatically time them
    out at 21:00:00 of that day.
    Called at startup (catch-up) and by the 9 PM scheduler.
    """
    from app.core.firestore_client import db, clients

    today     = date.today().isoformat()
    timed_out = 0

    for client_doc in clients().where("client_status", "==", True).stream():
        cdata = client_doc.to_dict()
        uid   = cdata.get("client_current_uid_log")
        if uid is None:
            # No log UID — just clear the status flag
            client_doc.reference.update({"client_status": False})
            timed_out += 1
            continue

        # Find the open log entry
        results = list(
            db.collection_group("logs")
            .where("log_uid", "==", uid)
            .stream()
        )
        if not results:
            client_doc.reference.update({"client_status": False})
            timed_out += 1
            continue

        log_data = results[0].to_dict()
        log_date = log_data.get("log_date", "")

        # Only auto-timeout logs from a previous day
        if log_date and log_date < today:
            results[0].reference.update({"time_out": "21:00:00"})
            client_doc.reference.update({
                "client_status":          False,
                "client_current_uid_log": None,
            })
            timed_out += 1
            log.info(
                f"Auto-timeout: {cdata.get('client_name')} "
                f"(log {uid} from {log_date}) timed out at 21:00:00")

    if timed_out:
        log.info(f"Auto-timeout complete: {timed_out} session(s) closed")


def start_nightly_timeout_scheduler() -> None:
    """
    Background thread that fires auto_timeout_stale_sessions every day at 21:00.
    Started once from on_startup.
    """
    import threading
    import time as _time

    log.info("Nightly scheduler starting...")

    def _loop():
        while True:
            now  = date.today()
            from datetime import datetime
            next_9pm = datetime(now.year, now.month, now.day, 21, 0, 0)
            current  = datetime.now()
            if current >= next_9pm:
                # Already past 9 PM today — schedule for tomorrow
                from datetime import timedelta as _td
                tomorrow = (now + _td(days=1))
                next_9pm = datetime(tomorrow.year, tomorrow.month,
                                    tomorrow.day, 21, 0, 0)
            wait_secs = (next_9pm - current).total_seconds()
            log.info(f"Nightly timeout scheduler: next run in "
                     f"{wait_secs/3600:.1f}h at {next_9pm.strftime('%H:%M')}")
            _time.sleep(wait_secs)
            try:
                auto_timeout_stale_sessions()
            except Exception as e:
                log.error(f"Nightly auto-timeout error: {e}")

    t = threading.Thread(target=_loop, daemon=True, name="NightlyTimeout")
    t.start()


def _tick_client(client_name: str, days: int) -> None:
    from app.core.firestore_client import db, clients, client_subs

    client_ref = clients().document(client_name)
    client_doc = client_ref.get()
    if not client_doc.exists:
        return
    client_data = client_doc.to_dict()

    # ── Tick active subscriptions ─────────────────────────────
    active_subs = list(
        client_subs(client_name).where("is_active", "==", True).stream()
    )

    if active_subs:
        batch = db.batch()
        post_tick = {}   # sub_id -> updated dict, to avoid second stream
        for s in active_subs:
            d = s.to_dict()
            days_rem    = max(0, d.get("days_remaining", 0) - days)
            hardcap_rem = d.get("trainer_hardcap_remaining", 0)
            trainer_rem = d.get("trainer_days_remaining", 0)
            is_active   = days_rem > 0

            if d.get("has_trainer", False) and hardcap_rem > 0:
                hardcap_rem = max(0, hardcap_rem - days)
                if hardcap_rem == 0:
                    trainer_rem = 0

            updated = {
                "days_remaining":            days_rem,
                "trainer_days_remaining":    trainer_rem,
                "trainer_hardcap_remaining": hardcap_rem,
                "is_active":                 is_active,
            }
            batch.update(s.reference, updated)
            post_tick[s.id] = {**d, **updated}
        batch.commit()
    else:
        post_tick = {}

    # ── Recalculate client totals from post-tick data ─────────
    # Use the already-fetched + updated values — no second Firestore read.
    still_active_data = [v for v in post_tick.values() if v.get("is_active")]
    total_days    = sum(v.get("days_remaining", 0)         for v in still_active_data)
    total_trainer = sum(v.get("trainer_days_remaining", 0) for v in still_active_data)
    expiry_dates  = [v.get("expires_at", "") for v in still_active_data
                     if v.get("expires_at")]
    last_expires  = max(expiry_dates) if expiry_dates else None

    # ── Tick lockers ──────────────────────────────────────────
    lockers = client_data.get("lockers", [])

    # Legacy migration: flat field → lockers list
    if not lockers and client_data.get("locker_number"):
        lockers = [{
            "locker_number":  client_data["locker_number"],
            "days_remaining": client_data.get("client_locker_days_remaining", 0),
            "expires_at":     None,
        }]

    updated_lockers = []
    for l in lockers:
        remaining = max(0, l.get("days_remaining", 0) - days)
        if remaining > 0:
            updated_lockers.append({**l, "days_remaining": remaining})
        # else: locker expired — drop it from the list

    # Sync legacy flat fields
    total_locker_days = sum(l["days_remaining"] for l in updated_lockers)
    primary_locker    = updated_lockers[0]["locker_number"] if updated_lockers else None

    updates = {
        "client_days_remaining":         total_days,
        "client_trainer_days_remaining": total_trainer,
        "client_locker_days_remaining":  total_locker_days,
        "last_plan_expires_at":          last_expires,
        "lockers":                       updated_lockers,
        "locker_number":                 primary_locker,
    }

    client_ref.update(updates)