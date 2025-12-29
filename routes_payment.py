from fastapi import APIRouter, Depends
from auth.dependencies import auth_required
from supabase_client import supabase
from pydantic import BaseModel
from datetime import date

router = APIRouter(prefix="/ledger", tags=["Ledger"])

class LedgerEntry(BaseModel):
    customer_id: str
    amount: float
    type: str  # debit / credit
    description: str | None = None
    due_date: date | None = None

@router.post("/add")
def add_ledger(entry: LedgerEntry, user=Depends(auth_required)):
    res = supabase.table("customer_ledger").insert({
        "store_id": user["store_id"],
        "customer_id": entry.customer_id,
        "amount": entry.amount,
        "type": entry.type,
        "description": entry.description,
        "due_date": entry.due_date
    }).execute()
    return res.data

@router.get("/customer/{customer_id}")
def get_customer_ledger(customer_id: str, user=Depends(auth_required)):
    res = supabase.table("customer_ledger") \
        .select("*") \
        .eq("store_id", user["store_id"]) \
        .eq("customer_id", customer_id) \
        .execute()
    return res.data
