# reminder_scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from supabase_client import supabase
from whatsapp_service import send_text_message
import config
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
sched = BackgroundScheduler()

def check_and_send_reminders():
    now = datetime.now(timezone.utc)
    # select reminders due now or earlier and not sent
    res = supabase.table("reminders").select("*").lte("due_date", now.isoformat()).eq("sent", False).execute()
    if not res.data:
        return
    for r in res.data:
        try:
            # get vendor config
            cfg = supabase.table("vendor_whatsapp").select("*").eq("store_id", r["store_id"]).single().execute()
            if not cfg.data:
                logger.warning("No whatsapp config for store %s", r["store_id"])
                continue
            to = str(r["customer_phone"]).lstrip("+").replace(" ", "")
            body = f"Hi {r.get('customer_name','')}, you have an amount due of ₹{float(r['amount']):.2f}. Please pay. - {config.APP_NAME}"
            send_text_message(cfg.data["phone_number_id"], cfg.data["access_token"], to, body)
            # mark sent (if repeating, logic can update due_date instead)
            supabase.table("reminders").update({"sent": True}).eq("id", r["id"]).execute()
        except Exception as e:
            logger.exception("Failed reminder send for id %s: %s", r["id"], e)

def start_scheduler():
    sched.add_job(check_and_send_reminders, "interval", seconds=60, id="reminder_job", replace_existing=True)
    sched.start()

def stop_scheduler():
    sched.shutdown()
