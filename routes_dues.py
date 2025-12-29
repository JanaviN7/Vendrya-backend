from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime

router = APIRouter(prefix="/dues", tags=["Customer Dues"])

# -------------------
# SCHEMAS
# -------------------
class AddCustomer(BaseModel):
    name: str
    phone: str | None = None

class AddTransaction(BaseModel):
    customer_id: str
    type: str   # "purchase" or "payment"
    amount: float
    note: str | None = None


# -------------------
# ADD CUSTOMER
# -------------------
@router.post("/customer/add")
def add_customer(payload: AddCustomer, user=Depends(auth_required)):
    data = supabase.table("customers").insert({
        "store_id": user["store_id"],
        "name": payload.name,
        "phone": payload.phone,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    return {"message": "Customer added", "customer": data.data[0]}


# -------------------
# ADD LEDGER ENTRY
# -------------------
@router.post("/transaction/add")
def add_transaction(payload: AddTransaction, user=Depends(auth_required)):
    res = supabase.table("customer_ledger").insert({
        "store_id": user["store_id"],
        "customer_id": payload.customer_id,
        "type": payload.type,
        "amount": payload.amount,
        "note": payload.note,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    return {"message": "Transaction saved", "entry": res.data[0]}


# -------------------
# CUSTOMER BALANCE
# -------------------
@router.get("/customer/{customer_id}/balance")
def customer_balance(customer_id: str, user=Depends(auth_required)):
    rows = supabase.table("customer_ledger") \
        .select("*") \
        .eq("customer_id", customer_id) \
        .execute()

    balance = 0
    for r in rows.data:
        if r["type"] == "purchase":
            balance += r["amount"]
        else:
            balance -= r["amount"]

    return {"balance": balance}


# -------------------
# CUSTOMER HISTORY
# -------------------
@router.get("/customer/{customer_id}/history")
def customer_history(customer_id: str, user=Depends(auth_required)):
    history = supabase.table("customer_ledger") \
        .select("*") \
        .eq("customer_id", customer_id) \
        .order("created_at", desc=True) \
        .execute()

    return {"history": history.data}
