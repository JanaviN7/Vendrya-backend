from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def generate_invoice(filename, customer, amount, items):
    c = canvas.Canvas(filename, pagesize=letter)
    y = 750

    c.drawString(50, y, "Vendora POS Invoice")
    y -= 30
    c.drawString(50, y, f"Customer: {customer}")
    y -= 20

    for item in items:
        c.drawString(50, y, f"{item['name']} - ₹{item['price']}")
        y -= 15

    y -= 20
    c.drawString(50, y, f"TOTAL: ₹{amount}")

    c.save()
    return filename
