from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List
from io import BytesIO
from datetime import datetime
import os

from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from supabase_client import supabase
from auth.dependencies import auth_required
from qr_utils import upi_deeplink, qr_png_base64_from_text
import base64


router = APIRouter(prefix="/invoice", tags=["Invoice"])


# -------------------------
# SCHEMAS
# -------------------------
class InvoiceItem(BaseModel):
    name: str
    quantity: int
    price: float
    line_total: float


class InvoiceRequest(BaseModel):
    customer_name: str = "Walk-in Customer"
    payment_mode: str = "cash"
    items: List[InvoiceItem]
    subtotal: float
    total_amount: float


# -------------------------
# FONT SETUP
# -------------------------
def _register_unicode_font():
    if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
        return

    font_paths = [
        os.path.join("fonts", "DejaVuSans.ttf"),
        os.path.join("fonts", "NotoSans-Regular.ttf"),
    ]

    for fp in font_paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("DejaVuSans", fp))
            return


def _get_store_profile(store_id: str) -> dict:
    store_res = (
        supabase.table("stores")
        .select("store_id,store_name")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )
    store_rows = store_res.data or []
    store = store_rows[0] if store_rows else {}

    settings_res = (
        supabase.table("store_settings")
        .select("upi_id,address,phone,gstin,logo_url")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )
    settings_rows = settings_res.data or []
    settings = settings_rows[0] if settings_rows else {}

    return {
        "store_name": store.get("store_name", "Smart POS Store"),
        "upi_id": settings.get("upi_id"),
        "address": settings.get("address"),
        "phone": settings.get("phone"),
        "gstin": settings.get("gstin"),
        "logo_url": settings.get("logo_url"),
    }


def _next_invoice_no(store_id: str) -> str:
    # ensure row exists
    supabase.table("invoice_counters").upsert({
        "store_id": store_id,
        "last_invoice_no": 0
    }).execute()

    res = (
        supabase.table("invoice_counters")
        .select("last_invoice_no")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )

    rows = res.data or []
    last_no = int(rows[0]["last_invoice_no"]) if rows else 0
    new_no = last_no + 1

    supabase.table("invoice_counters").update({
        "last_invoice_no": new_no,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("store_id", store_id).execute()

    return f"INV-{new_no:05d}"


def _download_logo_temp(logo_url: str) -> str | None:
    """
    Downloads store logo from Supabase public URL (if provided) to temp file.
    ReportLab Image needs a local file.
    """
    try:
        import requests
        os.makedirs("tmp", exist_ok=True)
        fp = os.path.join("tmp", "store_logo.png")
        r = requests.get(logo_url, timeout=5)
        if r.status_code == 200:
            with open(fp, "wb") as f:
                f.write(r.content)
            return fp
    except Exception:
        return None
    return None

@router.post("/generate")
def old_generate(payload: InvoiceRequest, user=Depends(auth_required)):
    return generate_invoice_pdf(payload, user)

# =====================================================
# ✅ A4 PDF INVOICE
# =====================================================
@router.post("/pdf")
def generate_invoice_pdf(payload: InvoiceRequest, user=Depends(auth_required)):
    try:
        _register_unicode_font()
        base_font = "DejaVuSans" if "DejaVuSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"

        store_id = user["store_id"]
        profile = _get_store_profile(store_id)
        invoice_no = _next_invoice_no(store_id)
        now_str = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=12 * mm,
            rightMargin=12 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("title", parent=styles["Title"], fontName=base_font, fontSize=16, alignment=1)
        normal = ParagraphStyle("normal", parent=styles["Normal"], fontName=base_font, fontSize=10)
        center_grey = ParagraphStyle("center_grey", parent=styles["Normal"], fontName=base_font, fontSize=10, alignment=1, textColor=colors.grey)

        elements = []

        # optional logo
        if profile.get("logo_url"):
            logo_fp = _download_logo_temp(profile["logo_url"])
            if logo_fp:
                elements.append(Image(logo_fp, width=35*mm, height=35*mm))
                elements.append(Spacer(1, 4))

        elements.append(Paragraph(profile["store_name"], title_style))
        if profile.get("address"):
            elements.append(Paragraph(profile["address"], center_grey))
        if profile.get("phone"):
            elements.append(Paragraph(f"Phone: {profile['phone']}", center_grey))
        if profile.get("gstin"):
            elements.append(Paragraph(f"GSTIN: {profile['gstin']}", center_grey))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph(f"<b>Invoice No:</b> {invoice_no}", normal))
        elements.append(Paragraph(f"<b>Date:</b> {now_str}", normal))
        elements.append(Paragraph(f"<b>Customer:</b> {payload.customer_name}", normal))
        elements.append(Paragraph(f"<b>Payment:</b> {payload.payment_mode.upper()}", normal))
        elements.append(Spacer(1, 10))

        # items table
        data = [["Item", "Qty", "Rate", "Amount"]]
        for it in payload.items:
            data.append([it.name, str(it.quantity), f"₹ {it.price:.2f}", f"₹ {it.line_total:.2f}"])

        table = Table(data, colWidths=[90*mm, 15*mm, 30*mm, 30*mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), base_font),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1f5f9")),
            ("GRID", (0,0), (-1,-1), 0.3, colors.lightgrey),
            ("ALIGN", (1,1), (-1,-1), "RIGHT"),
            ("BOTTOMPADDING", (0,0), (-1,0), 8),
            ("TOPPADDING", (0,0), (-1,0), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

        # totals
        totals_data = [
            ["Subtotal", f"₹ {payload.subtotal:.2f}"],
            ["Tax (0%)", "₹ 0.00"],
            ["TOTAL", f"₹ {payload.total_amount:.2f}"],
        ]
        totals_table = Table(totals_data, colWidths=[135*mm, 30*mm], hAlign="RIGHT")
        totals_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), base_font),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("ALIGN", (0,0), (-1,-1), "RIGHT"),
            ("LINEABOVE", (0,2), (-1,2), 1, colors.black),
            ("FONTSIZE", (0,2), (-1,2), 12),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 12))

        # UPI QR (optional)
        if profile.get("upi_id"):
            upi_link = upi_deeplink(profile["upi_id"], profile["store_name"], payload.total_amount, f"{invoice_no}")
            qr_b64 = qr_png_base64_from_text(upi_link)
            qr_bytes = base64.b64decode(qr_b64)
            qr_fp = os.path.join("tmp", f"qr_{invoice_no}.png")
            os.makedirs("tmp", exist_ok=True)
            with open(qr_fp, "wb") as f:
                f.write(qr_bytes)

            elements.append(Paragraph("<b>Scan to Pay (UPI)</b>", center_grey))
            elements.append(Spacer(1, 4))
            elements.append(Image(qr_fp, width=45*mm, height=45*mm))
            elements.append(Spacer(1, 6))

        elements.append(Paragraph("<b>Thank you for shopping!</b>", center_grey))
        elements.append(Paragraph("Visit again 😊", center_grey))

        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={invoice_no}.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# ✅ THERMAL RECEIPT (80mm)
# =====================================================
@router.post("/thermal")
def generate_thermal_invoice(payload: InvoiceRequest, user=Depends(auth_required)):
    try:
        _register_unicode_font()
        base_font = "DejaVuSans" if "DejaVuSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"

        store_id = user["store_id"]
        profile = _get_store_profile(store_id)
        invoice_no = _next_invoice_no(store_id)
        now_str = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        width = 80 * mm
        height = (120 + len(payload.items) * 10 + (40 if profile.get("upi_id") else 0)) * mm

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(width, height))
        y = height - 10 * mm

        def draw_center(text, size=10):
            nonlocal y
            c.setFont(base_font, size)
            c.drawCentredString(width / 2, y, text)
            y -= 6 * mm

        def draw_left(text, size=9):
            nonlocal y
            c.setFont(base_font, size)
            c.drawString(5 * mm, y, text)
            y -= 5 * mm

        def line():
            nonlocal y
            c.setStrokeColor(colors.grey)
            c.line(5 * mm, y, width - 5 * mm, y)
            y -= 4 * mm

        # header
        draw_center(profile["store_name"], 12)
        draw_center("RECEIPT", 10)
        line()

        if profile.get("phone"):
            draw_center(f"Phone: {profile['phone']}", 9)
        if profile.get("gstin"):
            draw_center(f"GSTIN: {profile['gstin']}", 9)
        if profile.get("address"):
            draw_center(profile["address"][:30], 8)

        line()
        draw_left(f"Invoice: {invoice_no}")
        draw_left(f"Date: {now_str}")
        draw_left(f"Customer: {payload.customer_name}")
        draw_left(f"Pay: {payload.payment_mode.upper()}")
        line()

        # table header
        c.setFont(base_font, 9)
        c.drawString(5 * mm, y, "Item")
        c.drawRightString(width - 45 * mm, y, "Qty")
        c.drawRightString(width - 5 * mm, y, "Amt")
        y -= 5 * mm
        line()

        for it in payload.items:
            name = it.name[:18]
            c.drawString(5 * mm, y, name)
            c.drawRightString(width - 45 * mm, y, str(it.quantity))
            c.drawRightString(width - 5 * mm, y, f"₹{it.line_total:.0f}")
            y -= 5 * mm

        line()

        # totals
        c.setFont(base_font, 10)
        c.drawRightString(width - 5 * mm, y, f"Subtotal: ₹{payload.subtotal:.2f}")
        y -= 6 * mm
        c.drawRightString(width - 5 * mm, y, "Tax: ₹0.00")
        y -= 6 * mm
        c.setFont(base_font, 11)
        c.drawRightString(width - 5 * mm, y, f"TOTAL: ₹{payload.total_amount:.2f}")
        y -= 8 * mm
        line()

        # upi qr
        if profile.get("upi_id"):
            draw_center("Scan to Pay (UPI)", 9)
            upi_link = upi_deeplink(profile["upi_id"], profile["store_name"], payload.total_amount, invoice_no)
            qr_b64 = qr_png_base64_from_text(upi_link)
            qr_bytes = base64.b64decode(qr_b64)
            qr_fp = os.path.join("tmp", f"qr_{invoice_no}_thermal.png")
            os.makedirs("tmp", exist_ok=True)
            with open(qr_fp, "wb") as f:
                f.write(qr_bytes)
            c.drawImage(qr_fp, width/2 - 15*mm, y-30*mm, width=30*mm, height=30*mm, mask='auto')
            y -= 34*mm
            line()

        draw_center("Thank you for shopping!", 10)
        draw_center("Visit again 😊", 9)

        c.showPage()
        c.save()

        pdf_bytes = buffer.getvalue()
        buffer.close()

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={invoice_no}_receipt.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
