import os
from datetime import timedelta
from datetime import datetime

def today():
    return datetime.now().strftime("%d %b %Y")



SUPABASE_URL= "https://usnuebgaeqttlvcwxfpw.supabase.co"
SUPABASE_KEY= "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVzbnVlYmdhZXF0dGx2Y3d4ZnB3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjIyNjAxNjYsImV4cCI6MjA3NzgzNjE2Nn0.fheUtal9s2O759VsPOly1N2hY6HsheG9J5zxizPuu5w"
JWT_SECRET = "supersecretkey"
JWT_ALGORITHM = "HS256"

JWT_EXPIRY_DAYS = 7
OTP_EXPIRY_MINUTES = 10

# Gmail SMTP credentials
GMAIL_USER = "janavi.nathwani9@gmail.com"
GMAIL_APP_PASSWORD = "vooeicmnljzncwqz"


# WHATSAPP_TOKEN = "PASTE_ACCESS_TOKEN_HERE"
# WHATSAPP_PHONE_ID = "PASTE_PHONE_NUMBER_ID_HERE"
# WHATSAPP_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_ID}/messages"
# =====================
# RAZORPAY — swap these with real keys when account is approved
# Get from: https://dashboard.razorpay.com/app/keys
# =====================
RAZORPAY_KEY_ID = "rzp_live_SQ25UWgpKvV2y1"       # ← paste your Key ID here
RAZORPAY_KEY_SECRET = "Olt1k2VDHA04WQkGKetew71W"    # ← paste your Key Secret here
RAZORPAY_WEBHOOK_SECRET = "Vendora@2016"          # ← set in Razorpay dashboard > Webhooks

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
