"""Generate the buyer's official receipt as a downloadable PDF.

Kept dependency-light: reportlab draws a clean branded receipt directly —
no headless browser or system libraries needed.
"""

import io

from django.utils import timezone
from django.utils.dateformat import format as date_format
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _money(cents):
    # Base-14 PDF fonts have no ₱ glyph; official PH receipts commonly use "Php".
    return f"Php {int(cents) // 100:,}.{int(cents) % 100:02d}"


def build_receipt_pdf(order, items, payment_method="", license_keys=()):
    """Return PDF bytes for the order's official receipt."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Virtus Receipt {str(order.id)[:8]}",
        author="Virtus",
    )

    styles = getSampleStyleSheet()
    ink = colors.HexColor("#111827")
    muted = colors.HexColor("#6b7280")
    brand_bg = colors.HexColor("#0b0b0c")

    title = ParagraphStyle("Brand", parent=styles["Title"], fontSize=22, textColor=ink, alignment=0)
    subtitle = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontSize=9.5, textColor=muted, spaceAfter=10
    )
    section = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontSize=12, textColor=ink, spaceBefore=12
    )
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, textColor=ink)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8.5, textColor=muted)

    story = [
        Paragraph("Virtus", title),
        Paragraph("Instant digital products · Official Receipt", subtitle),
    ]

    paid_on = (
        date_format(timezone.localtime(order.paid_at), "M j, Y g:i A")
        if order.paid_at
        else "Pending payment"
    )
    meta_rows = [
        ["Order #", str(order.id)[:8].upper()],
        ["Paid on", paid_on],
        [
            "Payment method",
            payment_method or ("Free checkout" if order.total_amount < 100 else "QR Ph / E-Wallet"),
        ],
        ["Receipt emailed to", order.email or "Not provided"],
    ]
    meta_table = Table(meta_rows, colWidths=[42 * mm, 110 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (0, -1), muted),
                ("TEXTCOLOR", (1, 0), (1, -1), ink),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story += [meta_table, Spacer(1, 6 * mm)]

    header_style = ParagraphStyle("CellHead", parent=styles["Normal"], fontSize=9, textColor=muted)
    item_rows = [[Paragraph("ITEM", header_style), "", Paragraph("PRICE", header_style)]]
    for item in items:
        ptype = item.product.get_product_type_display() if item.product_id else "Digital Product"
        item_rows.append(
            [
                Paragraph(f"<b>{item.product_name}</b>", body),
                Paragraph(ptype, small),
                Paragraph(_money(item.unit_price_cents), body),
            ]
        )
    totals = [["", "", ""]]
    if order.discount_amount:
        totals.append(["", "Discount", f"-{_money(order.discount_amount)}"])
    if order.total_amount < 100:
        totals.append(["", "Total (free checkout)", "Free"])
    else:
        totals.append(["", "Total paid", _money(order.total_amount)])

    items_table = Table(item_rows + totals, colWidths=[95 * mm, 35 * mm, 30 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#d1d5db")),
        ("LINEABOVE", (0, len(item_rows)), (-1, -1), 0.75, ink),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("FONTNAME", (0, len(item_rows)), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    items_table.setStyle(TableStyle(style))
    story += [Paragraph("Items", section), items_table]

    license_keys = list(license_keys)
    if license_keys:
        story.append(Paragraph("License keys / Access codes", section))
        key_data = [
            [
                Paragraph(f"<font face='Courier-Bold'>{k.key}</font>", body),
                Paragraph(k.order_item.product_name if k.order_item.product_id else "", small),
            ]
            for k in license_keys
        ]
        keys_table = Table(key_data, colWidths=[70 * mm, 90 * mm])
        keys_table.setStyle(
            TableStyle(
                [("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
            )
        )
        story.append(keys_table)

    memberships = [i for i in items if i.access_until]
    if memberships:
        story.append(Paragraph("Access windows", section))
        rows = []
        for i in memberships:
            until = date_format(timezone.localtime(i.access_until), "M j, Y")
            rows.append(
                [Paragraph(i.product_name, body), Paragraph(f"Access until {until}", small)]
            )
        mtable = Table(rows, colWidths=[70 * mm, 90 * mm])
        mtable.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 3)]))
        story.append(mtable)

    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "Thank you for shopping at Virtus! This receipt serves as proof of "
            "purchase for your records. Questions? Reply to your confirmation "
            "email with your order number.",
            small,
        )
    )
    story.append(
        Paragraph(
            "Secure checkout powered by PayMongo · QR Ph · GCash · Maya · BSP-regulated channels",
            small,
        )
    )

    doc.build(
        story,
        onFirstPage=lambda c, d: _brand_band(c, d, brand_bg),
        onLaterPages=lambda c, d: _brand_band(c, d, brand_bg),
    )
    return buffer.getvalue()


def _brand_band(canvas, doc, color):
    canvas.saveState()
    canvas.setFillColor(color)
    canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
    canvas.restoreState()
