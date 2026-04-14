from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta, date
from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/cash", tags=["Cash"])

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def today_ist():
    return now_ist().date()


# ==========================
# SCHEMAS
# ==========================

class CashOpenRequest(BaseModel):
    opening_balance: float
    note: Optional[str] = None


class CashCloseRequest(BaseModel):
    closing_balance: float    # actual cash counted
    note: Optional[str] = None


class DenominationCount(BaseModel):
    note_2000: int = 0
    note_500: int = 0
    note_200: int = 0
    note_100: int = 0
    note_50: int = 0
    note_20: int = 0
    note_10: int = 0
    coin_5: int = 0
    coin_2: int = 0
    coin_1: int = 0


class DenominationRequest(BaseModel):
    denominations: DenominationCount


# ==========================
# ✅ OPEN CASH DRAWER
# Admin sets opening balance at start of day
# ==========================

@router.post("/open")
def open_cash_drawer(payload: CashOpenRequest, user=Depends(auth_required)):
    """
    Record opening balance at start of day.
    Admin only.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can open cash drawer")

    store_id = user["store_id"]
    today = today_ist().isoformat()

    # Check if already opened today
    existing = supabase.table("cash_register") \
        .select("register_id, status") \
        .eq("store_id", store_id) \
        .eq("date", today) \
        .limit(1) \
        .execute()

    if existing.data:
        status = existing.data[0].get("status")
        if status == "open":
            raise HTTPException(
                status_code=400,
                detail="Cash drawer already opened for today. Close it first."
            )
        if status == "closed":
            raise HTTPException(
                status_code=400,
                detail="Today's cash register is already closed."
            )

    result = supabase.table("cash_register").insert({
        "store_id": store_id,
        "opened_by": user["user_id"],
        "date": today,
        "opening_balance": payload.opening_balance,
        "closing_balance": None,
        "expected_cash": None,
        "difference": None,
        "note": payload.note,
        "status": "open",
        "opened_at": now_ist().isoformat()
    }).execute()

    return {
        "success": True,
        "message": f"Cash drawer opened with Rs {payload.opening_balance:.2f}",
        "register": result.data[0] if result.data else None
    }


# ==========================
# ✅ CLOSE CASH DRAWER
# Admin counts cash at end of day
# System shows expected vs actual difference
# ==========================

@router.post("/close")
def close_cash_drawer(payload: CashCloseRequest, user=Depends(auth_required)):
    """
    Close cash drawer at end of day.
    Shows expected cash vs actual cash difference.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can close cash drawer")

    store_id = user["store_id"]
    today = today_ist().isoformat()

    # Get today's open register
    register_res = supabase.table("cash_register") \
        .select("*") \
        .eq("store_id", store_id) \
        .eq("date", today) \
        .eq("status", "open") \
        .single() \
        .execute()

    if not register_res.data:
        raise HTTPException(
            status_code=404,
            detail="No open cash drawer found for today. Please open first."
        )

    register = register_res.data
    opening_balance = float(register["opening_balance"])

    # Calculate expected cash from today's sales
    cash_sales_res = supabase.table("sales") \
        .select("total_amount, payment_mode") \
        .eq("store_id", store_id) \
        .gte("sale_timestamp", f"{today}T00:00:00") \
        .lte("sale_timestamp", f"{today}T23:59:59") \
        .execute()

    cash_collected = 0.0
    for sale in (cash_sales_res.data or []):
        mode = sale.get("payment_mode", "")
        amount = float(sale.get("total_amount", 0))

        if mode == "cash":
            cash_collected += amount
        elif "split" in mode:
            # Parse split payment cash portion
            # Format: "split|cash:150|upi:50"
            parts = mode.split("|")
            for part in parts:
                if part.startswith("cash:"):
                    try:
                        cash_collected += float(part.split(":")[1])
                    except:
                        pass

    # Cash refunds today
    cash_refunds_res = supabase.table("returns") \
        .select("refund_total, refund_mode") \
        .eq("store_id", store_id) \
        .eq("refund_mode", "cash") \
        .gte("return_timestamp", f"{today}T00:00:00") \
        .lte("return_timestamp", f"{today}T23:59:59") \
        .execute()

    cash_refunds = sum(
        float(r["refund_total"]) for r in (cash_refunds_res.data or [])
    )

    # Expected = opening + cash sales - cash refunds
    expected_cash = opening_balance + cash_collected - cash_refunds
    difference = payload.closing_balance - expected_cash

    # Update register
    supabase.table("cash_register") \
        .update({
            "closing_balance": payload.closing_balance,
            "expected_cash": round(expected_cash, 2),
            "cash_collected": round(cash_collected, 2),
            "cash_refunds": round(cash_refunds, 2),
            "difference": round(difference, 2),
            "note": payload.note,
            "status": "closed",
            "closed_at": now_ist().isoformat()
        }) \
        .eq("register_id", register["register_id"]) \
        .execute()

    # Status message based on difference
    if abs(difference) < 1:
        diff_message = "✅ Perfect! Cash matches exactly."
    elif difference > 0:
        diff_message = f"📈 Cash over by Rs {abs(difference):.2f}"
    else:
        diff_message = f"📉 Cash short by Rs {abs(difference):.2f}"

    return {
        "success": True,
        "message": "Cash drawer closed successfully",
        "summary": {
            "opening_balance": opening_balance,
            "cash_collected": round(cash_collected, 2),
            "cash_refunds": round(cash_refunds, 2),
            "expected_cash": round(expected_cash, 2),
            "actual_cash": payload.closing_balance,
            "difference": round(difference, 2),
            "difference_message": diff_message
        }
    }


# ==========================
# ✅ GET TODAY'S REGISTER STATUS
# ==========================

@router.get("/today")
def get_today_register(user=Depends(auth_required)):
    """Get today's cash register status."""
    store_id = user["store_id"]
    today = today_ist().isoformat()

    res = supabase.table("cash_register") \
        .select("*") \
        .eq("store_id", store_id) \
        .eq("date", today) \
        .limit(1) \
        .execute()

    if not res.data:
        return {
            "success": True,
            "status": "not_opened",
            "message": "Cash drawer not opened today",
            "register": None
        }

    register = res.data[0]
    return {
        "success": True,
        "status": register.get("status", "unknown"),
        "register": register
    }


# ==========================
# ✅ CASH REGISTER HISTORY
# ==========================

@router.get("/history")
def get_register_history(user=Depends(auth_required)):
    """Get last 30 days of cash register records."""
    store_id = user["store_id"]

    res = supabase.table("cash_register") \
        .select("*") \
        .eq("store_id", store_id) \
        .order("date", desc=True) \
        .limit(30) \
        .execute()

    return {
        "success": True,
        "history": res.data or []
    }


# ==========================
# ✅ DENOMINATION CALCULATOR
# Cashier enters denomination counts
# System calculates total and change
# ==========================

@router.post("/denominations/calculate")
def calculate_denominations(payload: DenominationRequest):
    """
    Calculate total cash from denomination counts.
    No auth needed — pure calculation endpoint.
    """
    d = payload.denominations
    denomination_values = {
        "note_2000": (d.note_2000, 2000),
        "note_500": (d.note_500, 500),
        "note_200": (d.note_200, 200),
        "note_100": (d.note_100, 100),
        "note_50": (d.note_50, 50),
        "note_20": (d.note_20, 20),
        "note_10": (d.note_10, 10),
        "coin_5": (d.coin_5, 5),
        "coin_2": (d.coin_2, 2),
        "coin_1": (d.coin_1, 1),
    }

    total = 0.0
    breakdown = []

    for key, (count, value) in denomination_values.items():
        if count > 0:
            amount = count * value
            total += amount
            breakdown.append({
                "denomination": value,
                "count": count,
                "amount": amount,
                "label": f"₹{value} × {count} = ₹{amount}"
            })

    return {
        "success": True,
        "total": round(total, 2),
        "breakdown": breakdown
    }


# ==========================
# ✅ CHANGE CALCULATOR
# Given bill amount + cash received → calculate change
# ==========================

class ChangeRequest(BaseModel):
    bill_amount: float
    cash_received: float


@router.post("/change/calculate")
def calculate_change(payload: ChangeRequest):
    """
    Calculate change to return to customer.
    Suggests optimal denomination breakdown for change.
    """
    if payload.cash_received < payload.bill_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Cash received Rs {payload.cash_received} is less than bill Rs {payload.bill_amount}"
        )

    change = round(payload.cash_received - payload.bill_amount, 2)

    # Calculate optimal denomination breakdown for change
    denominations = [2000, 500, 200, 100, 50, 20, 10, 5, 2, 1]
    remaining = int(change)  # work with integer for notes
    breakdown = []

    for denom in denominations:
        if remaining >= denom:
            count = remaining // denom
            remaining -= count * denom
            breakdown.append({
                "denomination": denom,
                "count": count,
                "amount": count * denom,
                "label": f"₹{denom} × {count}"
            })

    return {
        "success": True,
        "bill_amount": payload.bill_amount,
        "cash_received": payload.cash_received,
        "change": change,
        "change_breakdown": breakdown
    }