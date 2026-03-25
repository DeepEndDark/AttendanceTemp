from datetime import date, datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sqlalchemy.orm import Session


def generate_daily_report(db: Session, report_date: date):
    """
    Aggregate all closed sales for report_date, persist a DailyReport record,
    and return the report object. Idempotent — if report already exists, returns it.
    """
    from app.models.report import DailyReport, ReportItem
    from app.models.sales import SaleLog, SaleItem

    existing = db.query(DailyReport).filter(DailyReport.report_date == report_date).first()
    if existing:
        return existing

    closed_sales = db.query(SaleLog).filter(
        SaleLog.sale_date == report_date,
        SaleLog.sale_status == "closed",
    ).all()

    # Aggregate items
    aggregated: dict[str, dict] = {}
    for sale in closed_sales:
        for si in sale.item_list:
            if si.item_name not in aggregated:
                aggregated[si.item_name] = {"qty": 0, "value": 0.0}
            aggregated[si.item_name]["qty"] += si.item_qty
            aggregated[si.item_name]["value"] += si.item_total_price

    total_revenue = round(sum(v["value"] for v in aggregated.values()), 2)

    report = DailyReport(
        report_date=report_date,
        total_revenue=total_revenue,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(report)
    db.flush()

    for name, data in aggregated.items():
        db.add(ReportItem(
            report_date=report_date,
            item_name=name,
            total_qty_sold=data["qty"],
            total_value=round(data["value"], 2),
        ))

    db.commit()
    db.refresh(report)
    return report


def render_report_pdf(report) -> bytes:
    """Render a DailyReport ORM object as a PDF and return raw bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Daily Sales Report", styles["Title"]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(f"Date: {report.report_date}", styles["Normal"]))
    elements.append(Paragraph(
        f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 0.6 * cm))

    table_data = [["Item Name", "Qty Sold", "Stock Deducted", "Revenue"]]
    for item in sorted(report.items, key=lambda i: i.item_name):
        table_data.append([
            item.item_name,
            str(item.total_qty_sold),
            str(item.total_qty_sold),
            f"{item.total_value:.2f}",
        ])
    table_data.append(["", "", "TOTAL", f"{report.total_revenue:.2f}"])

    t = Table(table_data, colWidths=[7 * cm, 3 * cm, 4 * cm, 3.5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#185FA5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f5f5f5")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f3e8")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)

    doc.build(elements)
    return buf.getvalue()
