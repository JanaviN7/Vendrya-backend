from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import date

router = APIRouter(prefix="/reminders", tags=["Reminders"])

class Reminder(BaseModel):
    customer_id: str
    due_amount: float
    remind_on: date
    channel: str = "WHATSAPP"


@router.post("/add")
def add_reminder(rem: Reminder, user=Depends(auth_required)):
    supabase.table("reminders").insert({
        "store_id": user["store_id"],
        "customer_id": rem.customer_id,
        "due_amount": rem.due_amount,
        "remind_on": str(rem.remind_on),
        "channel": rem.channel
    }).execute()

    return {"message": "Reminder added"}


@router.get("/today")
def todays_reminders(user=Depends(auth_required)):
    today = date.today().isoformat()

    res = supabase.table("reminders") \
        .select("*") \
        .eq("remind_on", today) \
        .eq("store_id", user["store_id"]) \
        .eq("status", "PENDING") \
        .execute()

    return res.data
