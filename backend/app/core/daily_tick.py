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

    if tick_doc.exists:
        try:
            last = date.fromisoformat(
                tick_doc.to_dict().get("last_tick_date", ""))
        except ValueError:
            last = today - timedelta(days=1)
    else:
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
        for s in active_subs:
            d = s.to_dict()
            days_rem    = max(0, d.get("days_remaining", 0) - days)
            hardcap_rem = d.get("trainer_hardcap_remaining", 0)
            trainer_rem = d.get("trainer_days_remaining", 0)
            is_active   = days_rem > 0

            # Tick hardcap independently — zeroes trainer days if hit
            if d.get("has_trainer", False) and hardcap_rem > 0:
                hardcap_rem = max(0, hardcap_rem - days)
                if hardcap_rem == 0:
                    trainer_rem = 0

            batch.update(s.reference, {
                "days_remaining":          days_rem,
                "trainer_days_remaining":  trainer_rem,
                "trainer_hardcap_remaining": hardcap_rem,
                "is_active":               is_active,
            })
        batch.commit()

    # ── Recalculate client totals from active subs ────────────
    still_active = list(
        client_subs(client_name).where("is_active", "==", True).stream()
    )
    total_days    = sum(s.to_dict().get("days_remaining", 0)
                        for s in still_active)
    total_trainer = sum(s.to_dict().get("trainer_days_remaining", 0)
                        for s in still_active)

    # Last plan expiry — furthest expires_at among still-active subs
    expiry_dates = [s.to_dict().get("expires_at", "")
                    for s in still_active
                    if s.to_dict().get("expires_at")]
    last_expires = max(expiry_dates) if expiry_dates else None

    # ── Tick locker ───────────────────────────────────────────
    locker_days = client_data.get("client_locker_days_remaining", 0)
    locker_num  = client_data.get("locker_number")
    if locker_days > 0:
        locker_days = max(0, locker_days - days)

    updates = {
        "client_days_remaining":         total_days,
        "client_trainer_days_remaining": total_trainer,
        "client_locker_days_remaining":  locker_days,
        "last_plan_expires_at":          last_expires,
    }

    # Free locker when days hit 0
    if locker_num is not None and locker_days == 0:
        updates["locker_number"] = None

    client_ref.update(updates)
