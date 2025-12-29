from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta, timezone
import random
import smtplib
from email.message import EmailMessage
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


def send_email_otp(to_email: str, otp: str, purpose: str):
    msg = EmailMessage()
    msg["Subject"] = f"Your OTP for Vendora ({purpose})"
    msg["From"] = config.GMAIL_USER
    msg["To"] = to_email
    msg.set_content(
        f"""
Your OTP is: {otp}

Expires in {config.OTP_EXPIRY_MINUTES} minutes.

If you didn't request this, ignore this email.
"""
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        smtp.send_message(msg)


def create_jwt(payload: dict) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(days=config.JWT_EXPIRY_DAYS)
    payload["exp"] = expiry
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def validate_otp(email: str, otp: str, purpose: str):
    q = (
        supabase.table("otp_codes")
        .select("*")
        .eq("email", email)
        .eq("purpose", purpose)
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
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.OTP_EXPIRY_MINUTES
    )

    supabase.table("otp_codes").insert({
        "email": payload.email,
        "otp": otp,
        "purpose": "signup",
        "expires_at": expires_at.isoformat(),
        "used": False,
        "metadata": {
            "store_name": payload.store_name,
            "categories": payload.categories
        }
    }).execute()

    send_email_otp(payload.email, otp, "signup")
    return {"message": "OTP sent"}


@router.post("/signup/verify")
def signup_verify(payload: VerifySignupRequest):
    otp_row = validate_otp(payload.email, payload.otp, "signup")

    # Prevent duplicate signup
    existing = (
        supabase.table("store_users")
        .select("user_id")
        .eq("email", payload.email)
        .execute()
    )

    if existing.data:
        raise HTTPException(status_code=400, detail="User already exists")

    meta = otp_row.get("metadata") or {}

    # Create store
    store = supabase.table("stores").insert({
        "store_name": meta.get("store_name", "Unnamed Store"),
        "categories": meta.get("categories", []),
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    store_id = store.data[0]["store_id"]

    # Create admin
    user = supabase.table("store_users").insert({
        "store_id": store_id,
        "name": "Admin",
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

    return {"token": token, "store_id": store_id}


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
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.OTP_EXPIRY_MINUTES
    )

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

    user = (
        supabase.table("store_users")
        .select("*")
        .eq("email", payload.email)
        .limit(1)
        .execute()
        .data[0]
    )

    token = create_jwt({
        "user_id": user["user_id"],
        "store_id": user["store_id"],
        "role": user["role"],
        "email": user["email"]
    })

    return {
        "token": token,
        "role": user["role"],
        "store_id": user["store_id"]
    }
