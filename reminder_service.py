from apscheduler.schedulers.background import BackgroundScheduler
from whatsapp_service import send_whatsapp_message
from database import get_due_customers

def send_reminders():
    customers = get_due_customers()
    for c in customers:
        send_whatsapp_message(c["phone"],
            f"Reminder: ₹{c['amount']} pending at {c['store']}")

scheduler = BackgroundScheduler()
scheduler.add_job(send_reminders, 'interval', days=1)
scheduler.start()
