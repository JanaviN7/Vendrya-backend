import os
from datetime import timedelta
from datetime import datetime

def today():
    return datetime.now().strftime("%d %b %Y")



SUPABASE_URL= os.getenv("SUPABASE_URL")
SUPABASE_KEY= os.getenv("SUPABASE_KEY")
JWT_SECRET = os.getenv("JWT_SECRET","supersecretkey")
JWT_ALGORITHM = "HS256"

JWT_EXPIRY_DAYS = 7
OTP_EXPIRY_MINUTES = 10

# Gmail SMTP credentials (kept for reference, not used for OTP)
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


# WHATSAPP_TOKEN = "PASTE_ACCESS_TOKEN_HERE"
# WHATSAPP_PHONE_ID = "PASTE_PHONE_NUMBER_ID_HERE"
# WHATSAPP_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
# =====================
# RAZORPAY — swap these with real keys when account is approved
# Get from: https://dashboard.razorpay.com/app/keys
# =====================
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")          # ← set in Razorpay dashboard > Webhooks

# =====================
# BREVO — transactional email (replaces Resend)
# Get API key from: https://app.brevo.com/settings/keys/api
# Verify sender at: https://app.brevo.com/senders
# =====================
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "hello.vendrya@gmail.com")  # must be verified in Brevo

# categories
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