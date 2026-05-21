"""
Report generator — combined per-client layout for daily and monthly reports.
Format:
  DATE / MONTH header
  ─────────────────
  CLIENT: Name
    Item / Subscription   qty   cost
    CLIENT TOTAL               cost
  ─────────────────
  GRAND TOTAL                  cost
"""
from datetime import date, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable
)


def _header_color():
    return colors.HexColor("#185FA5")


def _build_pdf(title: str, subtitle: str, client_purchases: list[dict]) -> bytes:
    """
    client_purchases: list of {
        client_name: str,
        lines: [{name, qty, cost}],
        client_total: float
    }
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 0.4*cm))

    grand_total = 0.0

    for purchase in sorted(client_purchases, key=lambda x: x["client_name"]):
        elements.append(HRFlowable(width="100%", thickness=1,
                                   color=colors.HexColor("#cccccc")))
        elements.append(Spacer(1, 0.2*cm))

        # Client header
        elements.append(Paragraph(
            f"<b>CLIENT: {purchase['client_name']}</b>",
            styles["Normal"]
        ))
        elements.append(Spacer(1, 0.15*cm))

        # Line items
        table_data = []
        for line in purchase["lines"]:
            label = line["name"]
            if line.get("is_subscription"):
                label += " <i>(subscription)</i>"
            table_data.append([
                Paragraph(label, styles["Normal"]),
                f"x{line['qty']}",
                f"\u20b1{line['cost']:.2f}",
            ])

        # Client total row
        table_data.append([
            Paragraph("<b>CLIENT TOTAL</b>", styles["Normal"]),
            "",
            Paragraph(f"<b>\u20b1{purchase['client_total']:.2f}</b>", styles["Normal"]),
        ])

        t = Table(table_data, colWidths=[10*cm, 2*cm, 4*cm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -2),
             [colors.white, colors.HexColor("#f8f8f8")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f3e8")),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.3*cm))

        grand_total += purchase["client_total"]

    # Grand total
    elements.append(HRFlowable(width="100%", thickness=2,
                               color=_header_color()))
    elements.append(Spacer(1, 0.2*cm))
    gt = Table(
        [[Paragraph("<b>GRAND TOTAL</b>", styles["Normal"]),
          Paragraph(f"<b>\u20b1{grand_total:.2f}</b>", styles["Normal"])]],
        colWidths=[12*cm, 4*cm]
    )
    gt.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E6F1FB")),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(gt)

    doc.build(elements)
    return buf.getvalue()


def generate_daily_pdf(report_date: date, client_purchases: list[dict]) -> bytes:
    return _build_pdf(
        title="Daily Sales Report",
        subtitle=f"Date: {report_date.strftime('%B %d, %Y')}",
        client_purchases=client_purchases,
    )


def generate_monthly_pdf(year: int, month: int, client_purchases: list[dict]) -> bytes:
    from calendar import month_name
    return _build_pdf(
        title="Monthly Sales Report",
        subtitle=f"Month: {month_name[month]} {year}",
        client_purchases=client_purchases,
    )
