# qr_utils.py
import qrcode
import io
import base64
from urllib.parse import quote_plus

def upi_deeplink(payee_vpa: str, payee_name: str, amount: float | None = None, note: str | None = None) -> str:
    """
    Compose UPI deep link e.g. upi://pay?pa=vendor@upi&pn=Name&am=10&tn=note
    Many UPI apps handle this when clicked on mobile.
    """
    q = {
        "pa": payee_vpa,
        "pn": payee_name
    }
    if amount is not None:
        q["am"] = f"{amount:.2f}"
    if note:
        q["tn"] = note
    qs = "&".join(f"{k}={quote_plus(str(v))}" for k, v in q.items())
    return f"upi://pay?{qs}"

def qr_png_base64_from_text(text: str, box_size: int = 6) -> str:
    img = qrcode.make(text)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")
