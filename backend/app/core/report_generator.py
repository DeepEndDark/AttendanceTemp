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
    return colors.HexColor("#E8500A")


def _build_pdf(title: str, subtitle: str, client_purchases: list[dict]) -> bytes:
    """
    client_purchases: list of {
        client_name: str,
        lines: [{name, qty, cost, is_subscription, is_locker}],
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

    # ── Aggregate summaries from all lines ───────────────────
    item_totals: dict[str, dict] = {}         # name → {qty, revenue}
    subscription_totals: dict[str, dict] = {} # name → {qty, revenue}

    for purchase in client_purchases:
        for line in purchase["lines"]:
            name = line["name"]
            qty  = line.get("qty", 0)
            cost = line.get("cost", 0.0)
            if line.get("is_subscription"):
                d = subscription_totals.setdefault(
                    name, {"qty": 0, "revenue": 0.0})
            else:
                d = item_totals.setdefault(
                    name, {"qty": 0, "revenue": 0.0})
            d["qty"]     += qty
            d["revenue"] += cost

    # Title
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 0.4*cm))

    # ── Shared paragraph styles — safe against duplicate registration ─
    def _style(name, **kw):
        try:
            return styles[name]
        except KeyError:
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

    sec_style = _style("TigerSectionHdr",
                       fontSize=11, textColor=_header_color(), spaceAfter=4)

    # ── Items sold summary ───────────────────────────────────
    if item_totals:
        elements.append(Paragraph(
            "<b>ITEMS SOLD</b>", sec_style))
        elements.append(Spacer(1, 0.1*cm))

        hdr = [
            Paragraph("<b>Item</b>", styles["Normal"]),
            Paragraph("<b>Qty Sold</b>", styles["Normal"]),
            Paragraph("<b>Revenue</b>", styles["Normal"]),
        ]
        rows = [hdr]
        item_revenue_total = 0.0
        for name in sorted(item_totals):
            d = item_totals[name]
            rows.append([
                Paragraph(name, styles["Normal"]),
                str(d["qty"]),
                f"\u20b1{d['revenue']:.2f}",
            ])
            item_revenue_total += d["revenue"]
        rows.append([
            Paragraph("<b>Total</b>", styles["Normal"]),
            str(sum(d["qty"] for d in item_totals.values())),
            Paragraph(f"<b>\u20b1{item_revenue_total:.2f}</b>",
                      styles["Normal"]),
        ])

        t = Table(rows, colWidths=[10*cm, 2*cm, 4*cm])
        t.setStyle(TableStyle([
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
            ("BACKGROUND",    (0, 0), (-1,  0), _header_color()),
            ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
            ("ROWBACKGROUNDS",(0, 1), (-1, -2),
             [colors.white, colors.HexColor("#f8f8f8")]),
            ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#e8f3e8")),
            ("LINEABOVE",     (0, -1), (-1, -1), 0.5,
             colors.HexColor("#cccccc")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.4*cm))

    # ── Subscription plans sold summary ──────────────────────
    if subscription_totals:
        elements.append(Paragraph(
            "<b>SUBSCRIPTION PLANS SOLD</b>", sec_style))
        elements.append(Spacer(1, 0.1*cm))

        hdr = [
            Paragraph("<b>Plan</b>", styles["Normal"]),
            Paragraph("<b>Qty Sold</b>", styles["Normal"]),
            Paragraph("<b>Revenue</b>", styles["Normal"]),
        ]
        rows = [hdr]
        sub_revenue_total = 0.0
        for name in sorted(subscription_totals):
            d = subscription_totals[name]
            rows.append([
                Paragraph(name, styles["Normal"]),
                str(d["qty"]),
                f"\u20b1{d['revenue']:.2f}",
            ])
            sub_revenue_total += d["revenue"]
        rows.append([
            Paragraph("<b>Total</b>", styles["Normal"]),
            str(sum(d["qty"] for d in subscription_totals.values())),
            Paragraph(f"<b>\u20b1{sub_revenue_total:.2f}</b>",
                      styles["Normal"]),
        ])

        t = Table(rows, colWidths=[10*cm, 2*cm, 4*cm])
        t.setStyle(TableStyle([
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
            ("BACKGROUND",    (0, 0), (-1,  0), _header_color()),
            ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
            ("ROWBACKGROUNDS",(0, 1), (-1, -2),
             [colors.white, colors.HexColor("#f8f8f8")]),
            ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#e8f3e8")),
            ("LINEABOVE",     (0, -1), (-1, -1), 0.5,
             colors.HexColor("#cccccc")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.5*cm))

    # ── Per-client breakdown ──────────────────────────────────
    if client_purchases:
        elements.append(Paragraph(
            "<b>SALES BREAKDOWN BY CLIENT</b>", sec_style))
        elements.append(Spacer(1, 0.2*cm))

    grand_total = 0.0

    if not client_purchases:
        elements.append(Paragraph(
            "No sales recorded for this period.", styles["Normal"]))
    
    for purchase in sorted(client_purchases, key=lambda x: x["client_name"]):
        elements.append(Spacer(1, 0.2*cm))

        # Build rows: client name spans header, then item rows, then total
        table_data = []

        # Row 0 — client name banner spanning all columns
        table_data.append([
            Paragraph(f"<b>{purchase['client_name']}</b>", styles["Normal"]),
            "", "", "",
        ])

        # Row 1 — column headers
        table_data.append([
            Paragraph("<b>Item</b>", styles["Normal"]),
            Paragraph("<b>Type</b>", styles["Normal"]),
            Paragraph("<b>Qty</b>",  styles["Normal"]),
            Paragraph("<b>Subtotal</b>", styles["Normal"]),
        ])

        for line in purchase["lines"]:
            kind = "Subscription" if line.get("is_subscription") else "Item"
            table_data.append([
                Paragraph(line["name"], styles["Normal"]),
                kind,
                str(line["qty"]),
                f"\u20b1{line['cost']:.2f}",
            ])

        # Total row
        table_data.append([
            Paragraph("<b>CLIENT TOTAL</b>", styles["Normal"]),
            "", "",
            Paragraph(f"<b>\u20b1{purchase['client_total']:.2f}</b>",
                      styles["Normal"]),
        ])

        n = len(table_data)
        t = Table(table_data, colWidths=[8*cm, 2.5*cm, 1.5*cm, 4*cm])
        t.setStyle(TableStyle([
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ALIGN",        (2, 0), (-1, -1), "RIGHT"),

            # Client name banner row
            ("SPAN",         (0, 0), (-1, 0)),
            ("BACKGROUND",   (0, 0), (-1, 0), _header_color()),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("TOPPADDING",   (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING",(0, 0), (-1, 0), 5),

            # Column header row
            ("BACKGROUND",   (0, 1), (-1, 1), colors.HexColor("#FFE4D4")),
            ("FONTSIZE",     (0, 1), (-1, 1), 9),

            # Item rows — alternating
            ("ROWBACKGROUNDS", (0, 2), (-1, n-2),
             [colors.white, colors.HexColor("#f8f8f8")]),

            # Total row
            ("SPAN",         (0, -1), (2, -1)),
            ("BACKGROUND",   (0, -1), (-1, -1), colors.HexColor("#e8f3e8")),
            ("LINEABOVE",    (0, -1), (-1, -1), 0.5,
             colors.HexColor("#cccccc")),

            ("TOPPADDING",   (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
            ("BOX",          (0, 0), (-1, -1), 0.5,
             colors.HexColor("#cccccc")),
        ]))
        elements.append(t)

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
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FFF0E8")),
        ("FONTSIZE",      (0, 0), (-1, -1), 11),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(gt)

    doc.build(elements)
    return buf.getvalue()


def generate_daily_pdf(report_date: date, client_purchases: list[dict],
                       plan: str | None = None) -> bytes:
    subtitle = f"Date: {report_date.strftime('%B %d, %Y')}"
    if plan:
        subtitle += f"  |  Plan: {plan}"
    return _build_pdf(
        title="Daily Sales Report",
        subtitle=subtitle,
        client_purchases=client_purchases,
    )


def generate_monthly_pdf(year: int, month: int, client_purchases: list[dict],
                         plan: str | None = None) -> bytes:
    from calendar import month_name
    subtitle = f"Month: {month_name[month]} {year}"
    if plan:
        subtitle += f"  |  Plan: {plan}"
    return _build_pdf(
        title="Monthly Sales Report",
        subtitle=subtitle,
        client_purchases=client_purchases,
    )


def generate_custom_pdf(start_str: str, end_str: str,
                        client_purchases: list[dict],
                        plan: str | None = None) -> bytes:
    start = date.fromisoformat(start_str)
    end   = date.fromisoformat(end_str)
    subtitle = (f"Period: {start.strftime('%B %d, %Y')} "
               f"to {end.strftime('%B %d, %Y')}")
    if plan:
        subtitle += f"  |  Plan: {plan}"
    return _build_pdf(
        title="Custom Range Sales Report",
        subtitle=subtitle,
        client_purchases=client_purchases,
    )