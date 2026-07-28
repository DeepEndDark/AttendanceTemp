from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from app.api.dependencies import require_admin
from app.core.firestore_client import db, clients as clients_col
from app.schemas.token import TokenData

router = APIRouter(prefix="/reports", tags=["reports"])


def _filter_purchases_by_plan(purchases: list[dict],
                              plan: str | None) -> list[dict]:
    """
    Restricts `purchases` to clients whose currently active subscription
    plans include `plan`. No-op if plan is None/empty.
    Mirrors the same filter the frontend applies to the on-screen report,
    so the exported PDF matches what's shown when a plan filter is active.

    Uses the same live collection_group reconciliation as the on-screen
    filter (see subscriptions.get_live_plan_holders) rather than trusting
    the denormalized active_subscription_names field directly — otherwise
    the export and the on-screen report could disagree if that field has
    drifted. Falls back to the cached field only if the live check itself
    fails (e.g. index still building), so an export never hard-fails.
    """
    if not plan:
        return purchases

    try:
        from app.api.v1.endpoints.subscriptions import get_live_plan_holders
        matching_names = set(get_live_plan_holders().get(plan, []))
    except Exception:
        matching_names = {
            doc.id
            for doc in clients_col().stream()
            if plan in (doc.to_dict().get("active_subscription_names") or [])
        }
    return [p for p in purchases if p["client_name"] in matching_names]


def _build_purchases(date_strs: set[str]) -> list[dict]:
    """
    Use collection_group("sales") to read across all date partitions.
    Avoids phantom-document problem entirely.
    """
    query = (db.collection_group("sales")
               .where("sale_status", "==", "closed"))

    client_purchases: dict[str, dict] = {}

    for sale_doc in query.stream():
        if not sale_doc.reference.path.startswith("sale_logs/"):
            continue
        parts = sale_doc.reference.path.split("/")
        d_str = parts[1] if len(parts) >= 4 else ""
        if d_str not in date_strs:
            continue

        sale  = sale_doc.to_dict()
        cname = sale.get("client_name", "Unknown")

        if cname not in client_purchases:
            client_purchases[cname] = {
                "client_name":  cname,
                "lines":        [],
                "client_total": 0.0,
            }

        for item_doc in sale_doc.reference.collection("items").stream():
            i = item_doc.to_dict()
            client_purchases[cname]["lines"].append({
                "name":            i.get("item_name", ""),
                "qty":             i.get("item_qty", 0),
                "cost":            i.get("item_total_price", 0.0),
                "is_subscription": i.get("is_subscription", False),
                "is_locker":       i.get("is_locker", False),
            })
            client_purchases[cname]["client_total"] += i.get(
                "item_total_price", 0.0)

    for v in client_purchases.values():
        v["client_total"] = round(v["client_total"], 2)

    return sorted(client_purchases.values(),
                  key=lambda x: x["client_name"])


# ── Daily ─────────────────────────────────────────────────────

@router.get("/daily/{date_str}")
def get_daily_report(date_str: str,
                     _: TokenData = Depends(require_admin)):
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD format")

    purchases = _build_purchases({date_str})
    total     = round(sum(p["client_total"] for p in purchases), 2)
    return {
        "report_date":   date_str,
        "total_revenue": total,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "purchases":     purchases,
    }


@router.get("/daily/{date_str}/pdf")
def get_daily_pdf(date_str: str,
                  plan: str | None = Query(None),
                  _: TokenData = Depends(require_admin)):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD format")

    purchases = _build_purchases({date_str})
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_daily_pdf
    pdf = generate_daily_pdf(d, purchases, plan=plan)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="daily_{date_str}.pdf"'},
    )


@router.get("/daily/{date_str}/xlsx")
def get_daily_xlsx(date_str: str,
                   plan: str | None = Query(None),
                   _: TokenData = Depends(require_admin)):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD format")

    purchases = _build_purchases({date_str})
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_daily_xlsx
    xlsx = generate_daily_xlsx(d, purchases, plan=plan)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument"
                   ".spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="daily_{date_str}.xlsx"'},
    )


# ── Monthly ───────────────────────────────────────────────────

@router.get("/monthly/{year}/{month}")
def get_monthly_report(year: int, month: int,
                       _: TokenData = Depends(require_admin)):
    _, last_day = monthrange(year, month)
    date_strs   = {
        date(year, month, d).isoformat()
        for d in range(1, last_day + 1)
    }
    purchases = _build_purchases(date_strs)
    total     = round(sum(p["client_total"] for p in purchases), 2)
    return {
        "year":          year,
        "month":         month,
        "total_revenue": total,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "purchases":     purchases,
    }


@router.get("/monthly/{year}/{month}/pdf")
def get_monthly_pdf(year: int, month: int,
                    plan: str | None = Query(None),
                    _: TokenData = Depends(require_admin)):
    _, last_day = monthrange(year, month)
    date_strs   = {
        date(year, month, d).isoformat()
        for d in range(1, last_day + 1)
    }
    purchases = _build_purchases(date_strs)
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_monthly_pdf
    pdf = generate_monthly_pdf(year, month, purchases, plan=plan)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="report_{year}_{month:02d}.pdf"'},
    )


@router.get("/monthly/{year}/{month}/xlsx")
def get_monthly_xlsx(year: int, month: int,
                     plan: str | None = Query(None),
                     _: TokenData = Depends(require_admin)):
    _, last_day = monthrange(year, month)
    date_strs   = {
        date(year, month, d).isoformat()
        for d in range(1, last_day + 1)
    }
    purchases = _build_purchases(date_strs)
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_monthly_xlsx
    xlsx = generate_monthly_xlsx(year, month, purchases, plan=plan)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument"
                   ".spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="report_{year}_{month:02d}.xlsx"'},
    )


# ── Custom date range ────────────────────────────────────────

def _date_range_strs(start_str: str, end_str: str) -> set[str]:
    try:
        start = date.fromisoformat(start_str)
        end   = date.fromisoformat(end_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD format")
    if end < start:
        raise HTTPException(
            status_code=400,
            detail="End date must be on or after start date")
    span_days = (end - start).days
    return {
        (start + timedelta(days=i)).isoformat()
        for i in range(span_days + 1)
    }


@router.get("/custom/{start_str}/{end_str}")
def get_custom_report(start_str: str, end_str: str,
                      _: TokenData = Depends(require_admin)):
    date_strs = _date_range_strs(start_str, end_str)
    purchases = _build_purchases(date_strs)
    total     = round(sum(p["client_total"] for p in purchases), 2)
    return {
        "start_date":    start_str,
        "end_date":      end_str,
        "total_revenue": total,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "purchases":     purchases,
    }


@router.get("/custom/{start_str}/{end_str}/pdf")
def get_custom_pdf(start_str: str, end_str: str,
                   plan: str | None = Query(None),
                   _: TokenData = Depends(require_admin)):
    date_strs = _date_range_strs(start_str, end_str)
    purchases = _build_purchases(date_strs)
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_custom_pdf
    pdf = generate_custom_pdf(start_str, end_str, purchases, plan=plan)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="report_{start_str}_to_{end_str}.pdf"'},
    )


@router.get("/custom/{start_str}/{end_str}/xlsx")
def get_custom_xlsx(start_str: str, end_str: str,
                    plan: str | None = Query(None),
                    _: TokenData = Depends(require_admin)):
    date_strs = _date_range_strs(start_str, end_str)
    purchases = _build_purchases(date_strs)
    purchases = _filter_purchases_by_plan(purchases, plan)
    from app.core.report_generator import generate_custom_xlsx
    xlsx = generate_custom_xlsx(start_str, end_str, purchases, plan=plan)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument"
                   ".spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="report_{start_str}_to_{end_str}.xlsx"'},
    )