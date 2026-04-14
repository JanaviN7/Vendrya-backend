from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime, timezone, timedelta, date
import httpx
import config

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

IST = timezone(timedelta(hours=5, minutes=30))

# ==========================
# SCHEMAS
# ==========================

class SaveVendorWhatsApp(BaseModel):
    phone_number_id: str
    access_token: str


class SendInvoiceRequest(BaseModel):
    phone: str
    customer_name: str
    sale_id: str
    total_amount: float
    payment_mode: str
    items: list                  # list of {name, qty, price}
    store_name: Optional[str] = "Our Store"


class SendDueReminderRequest(BaseModel):
    phone: str
    customer_name: str
    due_amount: float
    due_date: Optional[str] = None
    store_name: Optional[str] = "Our Store"


class BulkReminderRequest(BaseModel):
    min_due_amount: Optional[float] = 0    # only send to customers owing > this
    store_name: Optional[str] = None


# ==========================
# HELPERS
# ==========================

def get_store_whatsapp_config(store_id: str) -> dict:
    """Get WhatsApp config for a store (their own API keys)."""
    cfg = supabase.table("vendor_whatsapp") \
        .select("*") \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if cfg.data:
        return {
            "phone_number_id": cfg.data["phone_number_id"],
            "access_token": cfg.data["access_token"],
            "source": "store"
        }

    # Fall back to platform-level config (Ventsa's own keys)
    if config.WHATSAPP_PHONE_NUMBER_ID and config.WHATSAPP_ACCESS_TOKEN:
        return {
            "phone_number_id": config.WHATSAPP_PHONE_NUMBER_ID,
            "access_token": config.WHATSAPP_ACCESS_TOKEN,
            "source": "platform"
        }

    raise HTTPException(
        status_code=503,
        detail="WhatsApp not configured. Please add WhatsApp API credentials in Settings."
    )


def send_whatsapp_text(
    phone: str,
    message: str,
    phone_number_id: str,
    access_token: str
) -> dict:
    """Send a WhatsApp text message via Meta Cloud API."""
    to = phone.strip().replace(" ", "").lstrip("+")
    if not to.startswith("91") and len(to) == 10:
        to = "91" + to  # Add India country code

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"

    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": message}
            },
            timeout=10.0
        )
        response.raise_for_status()
        print(f"✅ WhatsApp sent to {to}")
        return {"success": True, "to": to}
    except Exception as e:
        print(f"⚠️ WhatsApp send failed to {to}: {str(e)}")
        return {"success": False, "error": str(e)}


def log_whatsapp_message(
    store_id: str,
    phone: str,
    message_type: str,
    status: str,
    customer_name: str = None
):
    """Log WhatsApp message for tracking monthly usage."""
    try:
        supabase.table("whatsapp_logs").insert({
            "store_id": store_id,
            "phone": phone,
            "message_type": message_type,
            "status": status,
            "customer_name": customer_name,
            "sent_at": datetime.now(IST).isoformat()
        }).execute()
    except Exception as e:
        print(f"WhatsApp log failed: {str(e)}")


# ==========================
# ✅ SAVE WHATSAPP CONFIG
# Store owner saves their own Meta API keys
# ==========================

@router.post("/config/{store_id}")
def save_whatsapp_config(
    store_id: str,
    payload: SaveVendorWhatsApp,
    user=Depends(auth_required)
):
    if user["store_id"] != store_id or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")

    res = supabase.table("vendor_whatsapp").upsert({
        "store_id": store_id,
        "phone_number_id": payload.phone_number_id,
        "access_token": payload.access_token,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }, on_conflict="store_id").execute()

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed saving config")

    return {"success": True, "message": "WhatsApp config saved ✅"}


# ==========================
# ✅ GET WHATSAPP CONFIG STATUS
# ==========================

@router.get("/config/status")
def get_whatsapp_status(user=Depends(auth_required)):
    store_id = user["store_id"]

    cfg = supabase.table("vendor_whatsapp") \
        .select("phone_number_id, updated_at") \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    # Get this month's usage
    now = datetime.now(IST)
    month_start = now.replace(day=1, hour=0, minute=0, second=0).isoformat()

    usage_res = supabase.table("whatsapp_logs") \
        .select("message_type", count="exact") \
        .eq("store_id", store_id) \
        .gte("sent_at", month_start) \
        .execute()

    messages_this_month = usage_res.count or 0

    return {
        "success": True,
        "configured": bool(cfg.data),
        "phone_number_id": cfg.data.get("phone_number_id") if cfg.data else None,
        "messages_this_month": messages_this_month,
        "plan_limit": 500   # Pro plan includes 500 messages/month
    }


# ==========================
# ✅ SEND INVOICE VIA WHATSAPP
# Called after completing a sale
# ==========================

@router.post("/send-invoice")
def send_invoice_whatsapp(
    payload: SendInvoiceRequest,
    background_tasks: BackgroundTasks,
    user=Depends(auth_required)
):
    """Send bill summary to customer via WhatsApp after sale."""
    store_id = user["store_id"]
    wa_config = get_store_whatsapp_config(store_id)

    # Build bill message
    items_text = "\n".join([
        f"  • {item.get('name', 'Item')} x{item.get('qty', 1)} = ₹{item.get('price', 0):.0f}"
        for item in payload.items[:8]  # max 8 items in message
    ])

    if len(payload.items) > 8:
        items_text += f"\n  ... and {len(payload.items) - 8} more items"

    message = f"""🧾 *Bill from {payload.store_name}*

Hello {payload.customer_name}! 👋

Your bill summary:
{items_text}

💰 *Total: ₹{payload.total_amount:.2f}*
💳 Payment: {payload.payment_mode.upper()}

Thank you for shopping with us! 🙏
_Powered by Ventsa_"""

    # Send in background
    background_tasks.add_task(
        send_whatsapp_text,
        payload.phone,
        message,
        wa_config["phone_number_id"],
        wa_config["access_token"]
    )

    # Log message
    background_tasks.add_task(
        log_whatsapp_message,
        store_id,
        payload.phone,
        "invoice",
        "queued",
        payload.customer_name
    )

    return {
        "success": True,
        "message": f"Invoice sending to {payload.phone} ✅"
    }


# ==========================
# ✅ SEND PAYMENT DUE REMINDER
# ==========================

@router.post("/send-reminder")
def send_due_reminder(
    payload: SendDueReminderRequest,
    background_tasks: BackgroundTasks,
    user=Depends(auth_required)
):
    """Send payment due reminder to a customer."""
    store_id = user["store_id"]
    wa_config = get_store_whatsapp_config(store_id)

    due_text = f" (due by {payload.due_date})" if payload.due_date else ""

    message = f"""⚠️ *Payment Reminder from {payload.store_name}*

Hello {payload.customer_name},

This is a friendly reminder that you have an outstanding balance of:

💰 *₹{payload.due_amount:.2f}*{due_text}

Please clear your dues at your earliest convenience.

For any queries, contact us directly.

Thank you 🙏
_{payload.store_name}_"""

    background_tasks.add_task(
        send_whatsapp_text,
        payload.phone,
        message,
        wa_config["phone_number_id"],
        wa_config["access_token"]
    )

    background_tasks.add_task(
        log_whatsapp_message,
        store_id,
        payload.phone,
        "reminder",
        "queued",
        payload.customer_name
    )

    return {
        "success": True,
        "message": f"Reminder sent to {payload.customer_name} ✅"
    }


# ==========================
# ✅ BULK DUE REMINDERS
# Send reminders to all customers with dues
# ==========================

@router.post("/send-bulk-reminders")
def send_bulk_reminders(
    payload: BulkReminderRequest,
    background_tasks: BackgroundTasks,
    user=Depends(auth_required)
):
    """Send payment reminders to all customers with pending dues."""
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can send bulk reminders")

    wa_config = get_store_whatsapp_config(store_id)

    # Get store name
    store_res = supabase.table("stores") \
        .select("store_name") \
        .eq("store_id", store_id) \
        .single() \
        .execute()
    store_name = payload.store_name or (
        store_res.data.get("store_name") if store_res.data else "Our Store"
    )

    # Get customers with dues
    customers_res = supabase.table("customers") \
        .select("name, phone, total_due") \
        .eq("store_id", store_id) \
        .gt("total_due", payload.min_due_amount) \
        .execute()

    customers = customers_res.data or []
    sent_count = 0
    skipped_count = 0

    for customer in customers:
        phone = customer.get("phone", "")
        if not phone or len(phone) < 10:
            skipped_count += 1
            continue

        due = float(customer.get("total_due", 0))
        if due <= 0:
            skipped_count += 1
            continue

        message = f"""⚠️ *Payment Reminder from {store_name}*

Hello {customer['name']},

You have an outstanding balance of *₹{due:.2f}*.

Please clear your dues when you visit next.

Thank you 🙏
_{store_name}_"""

        background_tasks.add_task(
            send_whatsapp_text,
            phone,
            message,
            wa_config["phone_number_id"],
            wa_config["access_token"]
        )

        background_tasks.add_task(
            log_whatsapp_message,
            store_id,
            phone,
            "bulk_reminder",
            "queued",
            customer["name"]
        )

        sent_count += 1

    return {
        "success": True,
        "sent": sent_count,
        "skipped": skipped_count,
        "message": f"Reminders queued for {sent_count} customers ✅"
    }


# ==========================
# ✅ SEND DAILY SALES SUMMARY
# Owner gets their day's summary on WhatsApp
# ==========================

@router.post("/daily-summary")
def send_daily_summary(
    background_tasks: BackgroundTasks,
    user=Depends(auth_required)
):
    """Send today's sales summary to store owner's WhatsApp."""
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can request summary")

    wa_config = get_store_whatsapp_config(store_id)

    today = datetime.now(IST).date().isoformat()

    # Get today's sales
    sales_res = supabase.table("sales") \
        .select("total_amount, payment_mode") \
        .eq("store_id", store_id) \
        .gte("sale_timestamp", f"{today}T00:00:00") \
        .lte("sale_timestamp", f"{today}T23:59:59") \
        .execute()

    sales = sales_res.data or []
    total = sum(float(s["total_amount"]) for s in sales)
    orders = len(sales)

    # Payment breakdown
    cash_total = sum(
        float(s["total_amount"]) for s in sales
        if s.get("payment_mode") == "cash"
    )
    upi_total = sum(
        float(s["total_amount"]) for s in sales
        if s.get("payment_mode") == "upi"
    )

    # Get owner phone
    owner_res = supabase.table("store_users") \
        .select("email") \
        .eq("store_id", store_id) \
        .eq("role", "admin") \
        .limit(1) \
        .execute()

    store_res = supabase.table("stores") \
        .select("store_name") \
        .eq("store_id", store_id) \
        .single() \
        .execute()
    store_name = store_res.data.get("store_name") if store_res.data else "Your Store"

    # Get owner's WhatsApp from settings
    settings_res = supabase.table("store_settings") \
        .select("phone") \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    owner_phone = settings_res.data.get("phone") if settings_res.data else None
    if not owner_phone:
        raise HTTPException(
            status_code=400,
            detail="Owner phone not set in store settings"
        )

    message = f"""📊 *Daily Summary — {store_name}*
📅 {today}

💰 Total Sales: *₹{total:.2f}*
🛒 Total Orders: *{orders}*

💵 Cash: ₹{cash_total:.2f}
📱 UPI: ₹{upi_total:.2f}

_Have a great day! — Ventsa_ 🚀"""

    background_tasks.add_task(
        send_whatsapp_text,
        owner_phone,
        message,
        wa_config["phone_number_id"],
        wa_config["access_token"]
    )

    return {
        "success": True,
        "message": "Daily summary sent to your WhatsApp ✅",
        "summary": {
            "total": total,
            "orders": orders,
            "cash": cash_total,
            "upi": upi_total
        }
    }


# ==========================
# ✅ GET WHATSAPP LOGS
# Show message history
# ==========================

@router.get("/logs")
def get_whatsapp_logs(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = supabase.table("whatsapp_logs") \
        .select("*") \
        .eq("store_id", store_id) \
        .order("sent_at", desc=True) \
        .limit(50) \
        .execute()

    return {
        "success": True,
        "logs": res.data or []
    }


# ==========================
# LEGACY SEND (keep for backward compat)
# ==========================

@router.post("/send")
def send_bill(
    phone: str = Query(...),
    amount: float = Query(...),
    customer: str | None = Query(None),
    store_id: str | None = Query(None),
):
    to = phone.strip().replace(" ", "").lstrip("+")
    if not to.startswith("91") and len(to) == 10:
        to = "91" + to

    if store_id:
        cfg = supabase.table("vendor_whatsapp") \
            .select("*") \
            .eq("store_id", store_id) \
            .single() \
            .execute()
        if not cfg.data:
            raise HTTPException(status_code=400, detail="No WhatsApp config for store")
        phone_number_id = cfg.data["phone_number_id"]
        access_token = cfg.data["access_token"]
    else:
        phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID
        access_token = config.WHATSAPP_ACCESS_TOKEN
        if not phone_number_id or not access_token:
            raise HTTPException(status_code=500, detail="WhatsApp credentials missing")

    body = f"Hello {customer + ', ' if customer else ''}your bill is ₹{amount:.2f}. Thank you!"
    return send_whatsapp_text(to, body, phone_number_id, access_token)