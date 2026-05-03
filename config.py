import os
from datetime import timedelta, datetime


def today():
    return datetime.now().strftime("%d %b %Y")


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7
OTP_EXPIRY_MINUTES = 10

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# =====================
# RAZORPAY
# =====================
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

# =====================
# BREVO — transactional email
# =====================
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "hello.ventsa@gmail.com")

# =====================
# ✅ GROQ — voice billing (free tier)
# Get key from: https://console.groq.com/keys
# =====================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# =====================
# ✅ WHATSAPP — Meta Cloud API (Elite plan)
# Get from: https://developers.facebook.com/apps
# =====================
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")

# =====================
# DEFAULT CATEGORIES
# =====================
DEFAULT_STORE_CATEGORIES = [
    "Groceries & General Store",
    "Dairy & Milk Products",
    "Bakery",
    "Stationery",
    "Hardware",
    "Pharmacy",
    "Fruits & Vegetables",
    "Snacks & Beverages",
    "Household & Cleaning",
    "Cosmetics & Personal Care"
]
