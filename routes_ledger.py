from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime

router = APIRouter(prefix="/ledger", tags=["Ledger"])

class LedgerEntry(BaseModel):
    customer_id: str
    description: str
    amount: float
    type: str  # DEBIT or CREDIT


@router.post("/add")
def add_ledger(entry: LedgerEntry, user=Depends(auth_required)):
    res = supabase.table("customer_ledger").insert({
        "store_id": user["store_id"],
        "customer_id": entry.customer_id,
        "description": entry.description,
        "amount": entry.amount,
        "type": entry.type,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    return {"message": "Ledger entry added", "data": res.data}


@router.get("/customer/{customer_id}")
def get_customer_ledger(customer_id: str, user=Depends(auth_required)):
    res = supabase.table("customer_ledger") \
        .select("*") \
        .eq("customer_id", customer_id) \
        .eq("store_id", user["store_id"]) \
        .order("created_at") \
        .execute()

    return res.data


@router.get("/balance/{customer_id}")
def get_balance(customer_id: str, user=Depends(auth_required)):
    data = supabase.table("customer_ledger") \
        .select("amount,type") \
        .eq("customer_id", customer_id) \
        .execute().data

    balance = 0
    for row in data:
        if row["type"] == "DEBIT":
            balance += row["amount"]
        else:
            balance -= row["amount"]

    return {"balance": balance}
