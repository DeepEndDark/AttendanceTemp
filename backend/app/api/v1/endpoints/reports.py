from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.core.report_generator import generate_daily_report, render_report_pdf
from app.models.report import DailyReport
from app.schemas.report import ReportItemRead, ReportRead
from app.schemas.token import TokenData

router = APIRouter(prefix="/reports", tags=["reports"])


def _to_read(r: DailyReport) -> ReportRead:
    return ReportRead(
        report_date=r.report_date.isoformat(),
        total_revenue=r.total_revenue,
        generated_at=r.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        items=[
            ReportItemRead(
                item_name=i.item_name,
                total_qty_sold=i.total_qty_sold,
                total_value=i.total_value,
            )
            for i in r.items
        ],
    )


@router.get("/", response_model=list[str])
def list_report_dates(_: TokenData = Depends(require_admin), db: Session = Depends(get_db)):
    """Return all dates that have a generated report."""
    rows = db.query(DailyReport.report_date).order_by(DailyReport.report_date.desc()).all()
    return [r.report_date.isoformat() for r in rows]


@router.get("/{date_str}", response_model=ReportRead)
def get_report(
    date_str: str,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    report = db.query(DailyReport).filter(DailyReport.report_date == d).first()
    if not report:
        # Generate on demand if not yet created
        report = generate_daily_report(db, d)
    return _to_read(report)


@router.get("/{date_str}/pdf")
def get_report_pdf(
    date_str: str,
    _: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    report = db.query(DailyReport).filter(DailyReport.report_date == d).first()
    if not report:
        report = generate_daily_report(db, d)

    pdf_bytes = render_report_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report_{date_str}.pdf"'},
    )
