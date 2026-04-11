from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
import csv

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

from supabase_client import supabase
from auth.dependencies import auth_required
from routes_subscription import check_plan_limit, DEMO_STORE_IDS

router = APIRouter(prefix="/export", tags=["Export"])


# =====================
# HELPERS
# =====================

def get_date_range(months: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 30)
    return start.isoformat(), end.isoformat()


def register_font():
    if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
        return "DejaVuSans"
    paths = [
        os.path.join("fonts", "DejaVuSans.ttf"),
        os.path.join("fonts", "NotoSans-Regular.ttf"),
    ]
    for fp in paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("DejaVuSans", fp))
            return "DejaVuSans"
    return "Helvetica"


def get_store_name(store_id: str) -> str:
    res = supabase.table("stores") \
        .select("store_name") \
        .eq("store_id", store_id) \
        .limit(1) \
        .execute()
    return (res.data or [{}])[0].get("store_name", "My Store")


# =====================
# ✅ EXPORT SALES — CSV
# =====================

@router.get("/sales/csv")
def export_sales_csv(
    months: int = Query(default=6, ge=1, le=6),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "export")

    start, end = get_date_range(months)

    sales = supabase.table("sales") \
        .select("*, sale_items(*)") \
        .eq("store_id", store_id) \
        .gte("created_at", start) \
        .lte("created_at", end) \
        .order("created_at", desc=True) \
        .execute()

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Invoice No", "Date", "Customer", "Payment Mode",
        "Subtotal (Rs)", "Discount (Rs)", "Total (Rs)",
        "Items"
    ])

    for sale in (sales.data or []):
        items_summary = " | ".join([
            f"{item.get('product_name', 'Item')} x{item.get('quantity', 1)}"
            for item in (sale.get("sale_items") or [])
        ])
        writer.writerow([
            sale.get("invoice_no", ""),
            sale.get("created_at", "")[:10],
            sale.get("customer_name", "Walk-in"),
            sale.get("payment_mode", ""),
            sale.get("subtotal", 0),
            sale.get("discount_amount", 0),
            sale.get("total_amount", 0),
            items_summary
        ])

    output.seek(0)
    filename = f"ventsa_sales_{months}months_{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# =====================
# ✅ EXPORT SALES — PDF
# =====================

@router.get("/sales/pdf")
def export_sales_pdf(
    months: int = Query(default=6, ge=1, le=6),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "export")

    start, end = get_date_range(months)
    store_name = get_store_name(store_id)
    font = register_font()

    sales = supabase.table("sales") \
        .select("*") \
        .eq("store_id", store_id) \
        .gte("created_at", start) \
        .lte("created_at", end) \
        .order("created_at", desc=True) \
        .execute()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=12*mm, bottomMargin=12*mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontName=font, fontSize=16,
                                  textColor=colors.HexColor("#4338ca"),
                                  alignment=1, spaceAfter=4)
    sub_style = ParagraphStyle("sub", fontName=font, fontSize=10,
                                textColor=colors.HexColor("#6b7280"),
                                alignment=1, spaceAfter=2)

    elements = []
    elements.append(Paragraph(store_name, title_style))
    elements.append(Paragraph(
        f"Sales Report — Last {months} months | Generated: {datetime.now().strftime('%d %b %Y')}",
        sub_style
    ))
    elements.append(HRFlowable(width="100%", thickness=1.5,
                                color=colors.HexColor("#6366f1"), spaceAfter=8))

    # Table header
    header = ["Invoice", "Date", "Customer", "Payment", "Total (Rs)"]
    data = [header]

    total_revenue = 0
    for sale in (sales.data or []):
        data.append([
            sale.get("invoice_no", "—"),
            sale.get("created_at", "")[:10],
            sale.get("customer_name", "Walk-in")[:20],
            sale.get("payment_mode", "").upper(),
            f"Rs {sale.get('total_amount', 0):.2f}",
        ])
        total_revenue += sale.get("total_amount", 0)

    # Summary row
    data.append(["", "", "", "TOTAL", f"Rs {total_revenue:.2f}"])

    col_widths = [30*mm, 25*mm, 50*mm, 25*mm, 35*mm]
    table = Table(data, colWidths=col_widths)
    last_row = len(data) - 1

    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ede9fe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#4338ca")),
        ("FONTNAME", (0, 0), (-1, 0), font),
        ("GRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#e5e7eb")),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
        ("BACKGROUND", (0, last_row), (-1, last_row), colors.HexColor("#ede9fe")),
        ("FONTNAME", (0, last_row), (-1, last_row), font),
        ("TEXTCOLOR", (3, last_row), (-1, last_row), colors.HexColor("#4338ca")),
        ("LINEABOVE", (0, last_row), (-1, last_row), 1.5, colors.HexColor("#6366f1")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 8))

    brand_style = ParagraphStyle("brand", fontName=font, fontSize=8,
                                  textColor=colors.HexColor("#9ca3af"), alignment=1)
    elements.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#e5e7eb"), spaceAfter=6))
    elements.append(Paragraph("Powered by Ventsa · Simple Billing. Smart Business.", brand_style))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    filename = f"ventsa_sales_{months}months_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# =====================
# ✅ EXPORT PRODUCTS — CSV
# (includes soft-deleted items)
# =====================

@router.get("/products/csv")
def export_products_csv(
    include_deleted: bool = Query(default=True),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "export")

    query = supabase.table("products") \
        .select("*") \
        .eq("store_id", store_id)

    if not include_deleted:
        query = query.eq("is_deleted", False)

    res = query.order("name").execute()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Category", "Price (Rs)", "Cost Price (Rs)",
        "Quantity", "Barcode", "Threshold Qty",
        "Has Variants", "Unit", "Status", "Created At"
    ])

    for p in (res.data or []):
        writer.writerow([
            p.get("name", ""),
            p.get("category", ""),
            p.get("price", 0),
            p.get("cost_price", ""),
            p.get("quantity", 0),
            p.get("barcode", ""),
            p.get("threshold_qty", 5),
            "Yes" if p.get("has_variants") else "No",
            p.get("unit", "unit"),
            "Deleted" if p.get("is_deleted") else "Active",
            p.get("created_at", "")[:10],
        ])

    output.seek(0)
    filename = f"ventsa_products_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# =====================
# ✅ EXPORT CUSTOMER LEDGER — CSV
# =====================

@router.get("/ledger/csv")
def export_ledger_csv(
    months: int = Query(default=6, ge=1, le=6),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "export")

    start, end = get_date_range(months)

    customers = supabase.table("customers") \
        .select("*, ledger_entries(*)") \
        .eq("store_id", store_id) \
        .execute()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Customer Name", "Phone", "Total Due (Rs)",
        "Entry Date", "Entry Type", "Amount (Rs)", "Note"
    ])

    for customer in (customers.data or []):
        entries = customer.get("ledger_entries") or []
        if not entries:
            writer.writerow([
                customer.get("name", ""),
                customer.get("phone", ""),
                customer.get("total_due", 0),
                "", "", "", ""
            ])
        for entry in entries:
            entry_date = entry.get("created_at", "")
            if entry_date >= start and entry_date <= end:
                writer.writerow([
                    customer.get("name", ""),
                    customer.get("phone", ""),
                    customer.get("total_due", 0),
                    entry_date[:10],
                    entry.get("entry_type", ""),
                    entry.get("amount", 0),
                    entry.get("note", ""),
                ])

    output.seek(0)
    filename = f"ventsa_ledger_{months}months_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# =====================
# ✅ EXPORT LEDGER — PDF
# =====================

@router.get("/ledger/pdf")
def export_ledger_pdf(user=Depends(auth_required)):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "export")

    store_name = get_store_name(store_id)
    font = register_font()

    customers = supabase.table("customers") \
        .select("name, phone, total_due") \
        .eq("store_id", store_id) \
        .order("total_due", desc=True) \
        .execute()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=12*mm, bottomMargin=12*mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontName=font, fontSize=16,
                                  textColor=colors.HexColor("#4338ca"),
                                  alignment=1, spaceAfter=4)
    sub_style = ParagraphStyle("sub", fontName=font, fontSize=10,
                                textColor=colors.HexColor("#6b7280"),
                                alignment=1, spaceAfter=2)

    elements = []
    elements.append(Paragraph(store_name, title_style))
    elements.append(Paragraph(
        f"Customer Ledger Report | Generated: {datetime.now().strftime('%d %b %Y')}",
        sub_style
    ))
    elements.append(HRFlowable(width="100%", thickness=1.5,
                                color=colors.HexColor("#6366f1"), spaceAfter=8))

    header = ["Customer Name", "Phone", "Total Due (Rs)"]
    data = [header]
    total_dues = 0

    for c in (customers.data or []):
        data.append([
            c.get("name", ""),
            c.get("phone", "—"),
            f"Rs {c.get('total_due', 0):.2f}",
        ])
        total_dues += c.get("total_due", 0)

    data.append(["", "TOTAL DUES", f"Rs {total_dues:.2f}"])

    col_widths = [80*mm, 50*mm, 45*mm]
    table = Table(data, colWidths=col_widths)
    last_row = len(data) - 1

    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ede9fe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#4338ca")),
        ("GRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#e5e7eb")),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
        ("BACKGROUND", (0, last_row), (-1, last_row), colors.HexColor("#ede9fe")),
        ("LINEABOVE", (0, last_row), (-1, last_row), 1.5, colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (1, last_row), (-1, last_row), colors.HexColor("#4338ca")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 8))
    brand_style = ParagraphStyle("brand", fontName=font, fontSize=8,
                                  textColor=colors.HexColor("#9ca3af"), alignment=1)
    elements.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#e5e7eb"), spaceAfter=6))
    elements.append(Paragraph("Powered by Ventsa · Simple Billing. Smart Business.", brand_style))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    filename = f"ventsa_ledger_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )