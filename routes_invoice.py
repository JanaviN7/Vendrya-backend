from fastapi import APIRouter
from fpdf import FPDF
import os
import uuid

router = APIRouter(prefix="/invoice", tags=["Invoice"])

@router.get("/generate")
def generate_invoice(customer: str, amount: float):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, "SMART POS INVOICE", ln=True)
    pdf.cell(200, 10, f"Customer: {customer}", ln=True)
    pdf.cell(200, 10, f"Amount: ₹{amount}", ln=True)

    filename = f"invoices/{uuid.uuid4()}.pdf"
    os.makedirs("invoices", exist_ok=True)
    pdf.output(filename)

    return {"file": filename}
