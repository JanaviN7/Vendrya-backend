import qrcode
from io import BytesIO
import base64

def generate_qr(upi_id: str, amount: float):
    upi_url = f"upi://pay?pa={upi_id}&am={amount}&cu=INR"

    qr = qrcode.make(upi_url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    return base64.b64encode(buffer.getvalue()).decode()
