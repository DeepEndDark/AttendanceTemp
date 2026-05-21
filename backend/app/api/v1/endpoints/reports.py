from calendar import monthrange
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from app.api.dependencies import require_admin
from app.core.firestore_client import db
from app.schemas.token import TokenData

router = APIRouter(prefix="/reports", tags=["reports"])


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
                  _: TokenData = Depends(require_admin)):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD format")

    purchases = _build_purchases({date_str})
    from app.core.report_generator import generate_daily_pdf
    pdf = generate_daily_pdf(d, purchases)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="daily_{date_str}.pdf"'},
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
                    _: TokenData = Depends(require_admin)):
    _, last_day = monthrange(year, month)
    date_strs   = {
        date(year, month, d).isoformat()
        for d in range(1, last_day + 1)
    }
    purchases = _build_purchases(date_strs)
    from app.core.report_generator import generate_monthly_pdf
    pdf = generate_monthly_pdf(year, month, purchases)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="report_{year}_{month:02d}.pdf"'},
    )
