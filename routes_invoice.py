from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from io import BytesIO
from datetime import datetime
import os

from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from supabase_client import supabase
from auth.dependencies import auth_required


router = APIRouter(prefix="/invoice", tags=["Invoice"])


# -------------------------
# SCHEMAS
# -------------------------
class InvoiceItem(BaseModel):
    name: str
    quantity: int
    price: float
    line_total: float
    discount_pct: Optional[float] = 0.0   # per-item discount %


class InvoiceRequest(BaseModel):
    customer_name: str = "Walk-in Customer"
    payment_mode: str = "cash"
    items: List[InvoiceItem]
    subtotal: float
    total_amount: float
    discount_pct: Optional[float] = 0.0   # total bill discount %
    discount_amount: Optional[float] = 0.0


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
    store = (store_res.data or [{}])[0]

    settings_res = (
        supabase.table("store_settings")
        .select("upi_id,address,phone,gstin,logo_url")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )
    settings = (settings_res.data or [{}])[0]

    return {
        "store_name": store.get("store_name", "My Store"),
        "upi_id": settings.get("upi_id"),
        "address": settings.get("address"),
        "phone": settings.get("phone"),
        "gstin": settings.get("gstin"),
        "logo_url": settings.get("logo_url"),
    }


def _next_invoice_no(store_id: str) -> str:
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
    last_no = int((res.data or [{"last_invoice_no": 0}])[0]["last_invoice_no"])
    new_no = last_no + 1

    supabase.table("invoice_counters").update({
        "last_invoice_no": new_no,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("store_id", store_id).execute()

    return f"INV-{new_no:05d}"


def _download_logo_temp(logo_url: str) -> str | None:
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


def _get_vendorago_logo_path() -> str | None:
    """Returns path to Vendorago logo if it exists in static folder."""
    paths = [
        os.path.join("static", "vendorago_logo.png"),
        os.path.join("assets", "vendorago_logo.png"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


@router.post("/generate")
def old_generate(payload: InvoiceRequest, user=Depends(auth_required)):
    return generate_invoice_pdf(payload, user)


# =====================================================
# ✅ A4 PDF INVOICE — REDESIGNED
# =====================================================
@router.post("/pdf")
def generate_invoice_pdf(payload: InvoiceRequest, user=Depends(auth_required)):
    try:
        _register_unicode_font()
        base_font = "DejaVuSans" if "DejaVuSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
        bold_font = base_font  # fallback — use same font

        store_id = user["store_id"]
        profile = _get_store_profile(store_id)
        invoice_no = _next_invoice_no(store_id)
        now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=12 * mm,
            bottomMargin=12 * mm,
        )

        styles = getSampleStyleSheet()

        def style(name, **kwargs):
            return ParagraphStyle(name, parent=styles["Normal"], fontName=base_font, **kwargs)

        store_name_style = style("store_name", fontSize=20, alignment=1, spaceAfter=2, textColor=colors.HexColor("#1e1b4b"))
        subtitle_style = style("subtitle", fontSize=10, alignment=1, textColor=colors.HexColor("#6b7280"), spaceAfter=2)
        label_style = style("label", fontSize=10, textColor=colors.HexColor("#374151"))
        footer_style = style("footer", fontSize=10, alignment=1, textColor=colors.HexColor("#6b7280"), spaceAfter=2)
        brand_style = style("brand", fontSize=9, alignment=1, textColor=colors.HexColor("#9ca3af"))
        thankyou_style = style("thankyou", fontSize=14, alignment=1, textColor=colors.HexColor("#4338ca"), spaceBefore=4)

        elements = []

        # ── Store logo (if uploaded) or store name ──
        if profile.get("logo_url"):
            logo_fp = _download_logo_temp(profile["logo_url"])
            if logo_fp:
                elements.append(Image(logo_fp, width=30*mm, height=30*mm, hAlign="CENTER"))
                elements.append(Spacer(1, 4))

        elements.append(Paragraph(profile["store_name"], store_name_style))

        if profile.get("address"):
            elements.append(Paragraph(profile["address"], subtitle_style))
        if profile.get("phone"):
            elements.append(Paragraph(f"📞 {profile['phone']}", subtitle_style))
        if profile.get("gstin"):
            elements.append(Paragraph(f"GSTIN: {profile['gstin']}", subtitle_style))

        elements.append(Spacer(1, 3))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#6366f1"), spaceAfter=6))

        # ── Invoice meta ──
        meta_data = [
            [Paragraph(f"<b>Invoice No:</b> {invoice_no}", label_style),
             Paragraph(f"<b>Date:</b> {now_str}", label_style)],
            [Paragraph(f"<b>Customer:</b> {payload.customer_name}", label_style),
             Paragraph(f"<b>Payment:</b> {payload.payment_mode.upper()}", label_style)],
        ]
        meta_table = Table(meta_data, colWidths=[90*mm, 80*mm])
        meta_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), base_font),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 8))

        # ── Items table ──
        header = [
            Paragraph("<b>Item</b>", label_style),
            Paragraph("<b>Qty</b>", label_style),
            Paragraph("<b>Rate</b>", label_style),
            Paragraph("<b>Disc%</b>", label_style),
            Paragraph("<b>Amount</b>", label_style),
        ]
        data = [header]

        for it in payload.items:
            disc = f"{it.discount_pct:.0f}%" if (it.discount_pct or 0) > 0 else "—"
            data.append([
                it.name,
                str(it.quantity),
                f"Rs {it.price:.2f}",
                disc,
                f"Rs {it.line_total:.2f}",
            ])

        col_widths = [80*mm, 15*mm, 28*mm, 18*mm, 30*mm]
        table = Table(data, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), base_font),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#ede9fe")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#4338ca")),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e5e7eb")),
            ("ALIGN", (1,1), (-1,-1), "RIGHT"),
            ("BOTTOMPADDING", (0,0), (-1,0), 8),
            ("TOPPADDING", (0,0), (-1,0), 8),
            ("BOTTOMPADDING", (0,1), (-1,-1), 5),
            ("TOPPADDING", (0,1), (-1,-1), 5),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f9fafb")]),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 8))

        # ── Totals ──
        totals_data = [
            ["Subtotal", f"Rs {payload.subtotal:.2f}"],
        ]
        if (payload.discount_pct or 0) > 0:
            totals_data.append([
                f"Discount ({payload.discount_pct:.0f}%)",
                f"- Rs {payload.discount_amount:.2f}"
            ])
        totals_data.append(["Tax (0%)", "Rs 0.00"])
        totals_data.append(["TOTAL", f"Rs {payload.total_amount:.2f}"])

        totals_table = Table(totals_data, colWidths=[138*mm, 32*mm], hAlign="RIGHT")
        total_row = len(totals_data) - 1
        totals_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), base_font),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("ALIGN", (0,0), (-1,-1), "RIGHT"),
            ("LINEABOVE", (0, total_row), (-1, total_row), 1.5, colors.HexColor("#6366f1")),
            ("FONTSIZE", (0, total_row), (-1, total_row), 13),
            ("TEXTCOLOR", (0, total_row), (-1, total_row), colors.HexColor("#4338ca")),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("TEXTCOLOR", (0,0), (-1,-2), colors.HexColor("#6b7280")),
        ]))
        elements.append(totals_table)

        # ── Divider ──
        elements.append(Spacer(1, 10))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=10))

        # ── Thank you section ──
        elements.append(Paragraph("Thank you for your purchase! 🙏", thankyou_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("We appreciate your business and look forward to serving you again.", footer_style))
        elements.append(Spacer(1, 8))

        # ── Vendorago branding (shown only if store has no custom logo) ──
        if not profile.get("logo_url"):
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb"), spaceAfter=6))
            elements.append(Paragraph("Powered by Vendorago · Simple Billing. Smart Business.", brand_style))
            elements.append(Paragraph("vendorago.lovable.app", brand_style))

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
# ✅ THERMAL RECEIPT (80mm) — REDESIGNED
# =====================================================
@router.post("/thermal")
def generate_thermal_invoice(payload: InvoiceRequest, user=Depends(auth_required)):
    try:
        _register_unicode_font()
        base_font = "DejaVuSans" if "DejaVuSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"

        store_id = user["store_id"]
        profile = _get_store_profile(store_id)
        invoice_no = _next_invoice_no(store_id)
        now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

        width = 80 * mm
        extra = 20 if (payload.discount_pct or 0) > 0 else 0
        height = (130 + len(payload.items) * 10 + extra) * mm

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(width, height))
        y = height - 8 * mm

        def draw_center(text, size=10, bold=False, color=None):
            nonlocal y
            c.setFont(base_font, size)
            if color:
                c.setFillColor(color)
            c.drawCentredString(width / 2, y, text)
            if color:
                c.setFillColor(colors.black)
            y -= 5.5 * mm

        def draw_left(text, size=9):
            nonlocal y
            c.setFont(base_font, size)
            c.drawString(5 * mm, y, text)
            y -= 5 * mm

        def line(thick=False):
            nonlocal y
            c.setStrokeColor(colors.HexColor("#6366f1") if thick else colors.HexColor("#d1d5db"))
            c.setLineWidth(1.5 if thick else 0.5)
            c.line(5 * mm, y, width - 5 * mm, y)
            y -= 4 * mm

        # ── Header ──
        draw_center(profile["store_name"], 13)
        if profile.get("address"):
            draw_center(profile["address"][:35], 8, color=colors.HexColor("#6b7280"))
        if profile.get("phone"):
            draw_center(f"Ph: {profile['phone']}", 8, color=colors.HexColor("#6b7280"))
        if profile.get("gstin"):
            draw_center(f"GSTIN: {profile['gstin']}", 8)

        line(thick=True)

        draw_left(f"Invoice: {invoice_no}")
        draw_left(f"Date:    {now_str}")
        draw_left(f"Customer: {payload.customer_name}")
        draw_left(f"Payment: {payload.payment_mode.upper()}")
        line()

        # ── Items ──
        c.setFont(base_font, 9)
        c.setFillColor(colors.HexColor("#4338ca"))
        c.drawString(5*mm, y, "Item")
        c.drawRightString(width - 35*mm, y, "Qty")
        c.drawRightString(width - 5*mm, y, "Amt")
        c.setFillColor(colors.black)
        y -= 5*mm
        line()

        for it in payload.items:
            name = it.name[:20]
            c.setFont(base_font, 9)
            c.drawString(5*mm, y, name)
            c.drawRightString(width - 35*mm, y, str(it.quantity))
            c.drawRightString(width - 5*mm, y, f"Rs{it.line_total:.0f}")
            if (it.discount_pct or 0) > 0:
                y -= 4*mm
                c.setFont(base_font, 7)
                c.setFillColor(colors.HexColor("#6b7280"))
                c.drawString(8*mm, y, f"  Disc: {it.discount_pct:.0f}%")
                c.setFillColor(colors.black)
            y -= 5*mm

        line()

        # ── Totals ──
        c.setFont(base_font, 9)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawRightString(width - 5*mm, y, f"Subtotal: Rs{payload.subtotal:.2f}")
        y -= 5*mm

        if (payload.discount_pct or 0) > 0:
            c.drawRightString(width - 5*mm, y, f"Discount ({payload.discount_pct:.0f}%): -Rs{payload.discount_amount:.2f}")
            y -= 5*mm

        c.drawRightString(width - 5*mm, y, "Tax: Rs0.00")
        y -= 5*mm

        c.setFillColor(colors.black)
        c.setFont(base_font, 12)
        c.setFillColor(colors.HexColor("#4338ca"))
        c.drawRightString(width - 5*mm, y, f"TOTAL: Rs{payload.total_amount:.2f}")
        c.setFillColor(colors.black)
        y -= 8*mm
        line(thick=True)

        # ── Thank you ──
        draw_center("Thank you for your purchase!", 10, color=colors.HexColor("#4338ca"))
        draw_center("Visit us again! 🙏", 9, color=colors.HexColor("#6b7280"))
        y -= 2*mm
        line()

        # ── Vendorago branding ──
        draw_center("Powered by Vendorago", 8, color=colors.HexColor("#9ca3af"))
        draw_center("vendorago.lovable.app", 7, color=colors.HexColor("#9ca3af"))

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