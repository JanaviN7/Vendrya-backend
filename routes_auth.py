# routes_auth.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta, timezone
import random
import string
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import jwt

import config
from supabase_client import supabase

router = APIRouter(prefix="/auth", tags=["Auth"])


# ================= SCHEMAS =================

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    store_name: str
    categories: list[str] | None = []


class VerifySignupRequest(BaseModel):
    email: EmailStr
    otp: str


class LoginRequest(BaseModel):
    email: EmailStr


class VerifyLoginRequest(BaseModel):
    email: EmailStr
    otp: str


# ================= HELPERS =================

def generate_otp(length: int = 6) -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def generate_store_code() -> str:
    for _ in range(10):
        digits = "".join(random.choices(string.digits, k=4))
        code = f"SHOP-{digits}"
        existing = supabase.table("stores").select("store_id").eq("store_code", code).execute()
        if not existing.data:
            return code
    digits = "".join(random.choices(string.digits, k=6))
    return f"SHOP-{digits}"


def send_email_otp(to_email: str, otp: str, purpose: str):
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        print(f"[DEV OTP] {purpose.upper()} OTP for {to_email}: {otp}")
        return

    try:
        subject = "Your Vendorago Verification Code"

        # ✅ Professional HTML email
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="500" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#6366f1,#14b8a6);padding:32px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">Vendorago</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">Simple Billing. Smart Business.</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 24px;">
              <p style="margin:0 0 8px;color:#374151;font-size:16px;font-weight:600;">
                {"Welcome to Vendorago! 👋" if purpose == "signup" else "Your Login Code"}
              </p>
              <p style="margin:0 0 28px;color:#6b7280;font-size:14px;line-height:1.6;">
                {"Thanks for signing up! Use the verification code below to complete your registration." if purpose == "signup" else "Use the code below to securely log in to your Vendorago account."}
              </p>

              <!-- OTP Box -->
              <div style="background:#f0f0ff;border:2px dashed #6366f1;border-radius:10px;padding:24px;text-align:center;margin-bottom:28px;">
                <p style="margin:0 0 6px;color:#6b7280;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Your verification code</p>
                <p style="margin:0;color:#4338ca;font-size:40px;font-weight:800;letter-spacing:12px;">{otp}</p>
              </div>

              <p style="margin:0 0 6px;color:#9ca3af;font-size:12px;text-align:center;">
                This code expires in <strong>{config.OTP_EXPIRY_MINUTES} minutes</strong>
              </p>
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                If you did not request this, you can safely ignore this email.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                © 2026 Vendorago &nbsp;·&nbsp; Built for Indian Retailers
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

        plain_body = f"""
Vendorago — Simple Billing. Smart Business.

Your verification code is: {otp}

This code expires in {config.OTP_EXPIRY_MINUTES} minutes.

If you did not request this, please ignore this email.

© 2026 Vendorago
"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Vendorago <{config.GMAIL_USER}>"
        msg["To"] = to_email

        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print("⚠️ Email sending failed:", str(e))


def create_jwt(payload: dict) -> str:
    data = payload.copy()
    expiry = datetime.now(timezone.utc) + timedelta(days=config.JWT_EXPIRY_DAYS)
    data["exp"] = expiry
    return jwt.encode(data, config.JWT_SECRET, algorithm="HS256")


def validate_otp(email: str, otp: str, purpose: str):
    q = (
        supabase.table("otp_codes")
        .select("*")
        .eq("email", email)
        .eq("purpose", purpose)
        .eq("otp", str(otp))
        .eq("used", False)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not q.data:
        raise HTTPException(status_code=400, detail="OTP not found")

    row = q.data[0]

    if str(row["otp"]) != str(otp):
        raise HTTPException(status_code=400, detail="Invalid OTP")

    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="OTP expired")

    supabase.table("otp_codes").update({"used": True}).eq("id", row["id"]).execute()
    return row


# ================= SIGNUP =================

@router.post("/signup/send-otp")
def signup_send_otp(payload: SignupRequest):
    otp = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.OTP_EXPIRY_MINUTES)

    supabase.table("otp_codes").insert({
        "email": payload.email,
        "otp": otp,
        "purpose": "signup",
        "expires_at": expires_at.isoformat(),
        "used": False,
        "metadata": {
            "name": payload.name,
            "store_name": payload.store_name,
            "categories": payload.categories
        }
    }).execute()

    send_email_otp(payload.email, otp, "signup")
    return {"message": "OTP sent"}


@router.post("/signup/verify")
def signup_verify(payload: VerifySignupRequest):
    otp_row = validate_otp(payload.email, payload.otp, "signup")

    existing = (
        supabase.table("store_users")
        .select("user_id")
        .eq("email", payload.email)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="User already exists")

    meta = otp_row.get("metadata") or {}
    store_code = generate_store_code()

    store = supabase.table("stores").insert({
        "store_name": meta.get("store_name", "Unnamed Store"),
        "categories": meta.get("categories", []),
        "store_code": store_code,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    store_id = store.data[0]["store_id"]

    user = supabase.table("store_users").insert({
        "store_id": store_id,
        "name": meta.get("name", "Admin"),
        "email": payload.email,
        "role": "admin",
        "created_at": datetime.utcnow().isoformat()
    }).execute().data[0]

    token = create_jwt({
        "user_id": user["user_id"],
        "store_id": store_id,
        "role": user["role"],
        "email": user["email"]
    })

    return {
        "token": token,
        "store_id": store_id,
        "store_code": store_code
    }


# ================= LOGIN =================

@router.post("/login/send-otp")
def login_send_otp(payload: LoginRequest):
    user = (
        supabase.table("store_users")
        .select("user_id")
        .eq("email", payload.email)
        .execute()
    )
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")

    otp = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.OTP_EXPIRY_MINUTES)

    supabase.table("otp_codes").insert({
        "email": payload.email,
        "otp": otp,
        "purpose": "login",
        "expires_at": expires_at.isoformat(),
        "used": False
    }).execute()

    send_email_otp(payload.email, otp, "login")
    return {"message": "OTP sent"}


@router.post("/login/verify")
def login_verify(payload: VerifyLoginRequest):
    validate_otp(payload.email, payload.otp, "login")

    res = (
        supabase.table("store_users")
        .select("*")
        .eq("email", payload.email)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")

    user = res.data[0]

    store_res = supabase.table("stores") \
        .select("store_code") \
        .eq("store_id", user["store_id"]) \
        .limit(1) \
        .execute()

    store_code = store_res.data[0]["store_code"] if store_res.data else None

    token = create_jwt({
        "user_id": user["user_id"],
        "store_id": user["store_id"],
        "role": user["role"],
        "email": user["email"]
    })

    return {
        "token": token,
        "role": user["role"],
        "store_id": user["store_id"],
        "store_code": store_code
    }