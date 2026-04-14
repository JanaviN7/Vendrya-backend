from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/customers", tags=["Customers"])

IST = timezone(timedelta(hours=5, minutes=30))


# ==========================
# SCHEMAS
# ==========================

class BillNoteUpdate(BaseModel):
    sale_id: str
    note: str


# ==========================
# ✅ GET CUSTOMER PURCHASE HISTORY
# Shows past purchases when customer name is entered in POS
# ==========================

@router.get("/history")
def get_customer_history(
    name: str = Query(..., description="Customer name to search"),
    limit: int = Query(default=5, le=20),
    user=Depends(auth_required)
):
    """
    Get purchase history for a customer by name.
    Called when cashier types customer name in POS.
    Returns last N purchases with items.
    """
    store_id = user["store_id"]

    # Find sales by customer name (partial match)
    sales_res = supabase.table("sales") \
        .select("sale_id, customer_name, total_amount, payment_mode, sale_timestamp, status") \
        .eq("store_id", store_id) \
        .ilike("customer_name", f"%{name.strip()}%") \
        .order("sale_timestamp", desc=True) \
        .limit(limit) \
        .execute()

    sales = sales_res.data or []

    if not sales:
        return {
            "success": True,
            "customer_name": name,
            "total_visits": 0,
            "total_spent": 0,
            "last_visit": None,
            "purchases": []
        }

    # Get items for each sale
    sale_ids = [s["sale_id"] for s in sales]
    items_res = supabase.table("sale_items") \
        .select("sale_id, product_name, quantity, price, total") \
        .in_("sale_id", sale_ids) \
        .execute()

    # Group items by sale_id
    items_by_sale = {}
    for item in (items_res.data or []):
        sid = item["sale_id"]
        if sid not in items_by_sale:
            items_by_sale[sid] = []
        items_by_sale[sid].append({
            "name": item.get("product_name", "Unknown"),
            "quantity": item.get("quantity", 1),
            "price": item.get("price", 0),
            "total": item.get("total", 0)
        })

    # Build purchase history
    purchases = []
    total_spent = 0.0

    for sale in sales:
        sid = sale["sale_id"]
        total_spent += float(sale.get("total_amount", 0))
        purchases.append({
            "sale_id": sid,
            "date": sale.get("sale_timestamp", "")[:10],
            "time": sale.get("sale_timestamp", "")[11:16],
            "total_amount": float(sale.get("total_amount", 0)),
            "payment_mode": sale.get("payment_mode", "cash"),
            "status": sale.get("status", "completed"),
            "items": items_by_sale.get(sid, []),
            "items_count": len(items_by_sale.get(sid, []))
        })

    # Get all-time stats for this customer
    all_sales_res = supabase.table("sales") \
        .select("total_amount") \
        .eq("store_id", store_id) \
        .ilike("customer_name", f"%{name.strip()}%") \
        .execute()

    all_time_total = sum(
        float(s["total_amount"]) for s in (all_sales_res.data or [])
    )

    return {
        "success": True,
        "customer_name": name,
        "total_visits": len(all_sales_res.data or []),
        "total_spent": round(all_time_total, 2),
        "last_visit": sales[0].get("sale_timestamp", "")[:10] if sales else None,
        "recent_purchases": purchases
    }


# ==========================
# ✅ GET CUSTOMER SUGGESTIONS
# Auto-complete customer names while typing
# ==========================

@router.get("/suggestions")
def get_customer_suggestions(
    q: str = Query(..., min_length=1),
    user=Depends(auth_required)
):
    """
    Get customer name suggestions for autocomplete.
    Called as cashier types in customer name field.
    """
    store_id = user["store_id"]

    res = supabase.table("sales") \
        .select("customer_name") \
        .eq("store_id", store_id) \
        .ilike("customer_name", f"%{q.strip()}%") \
        .neq("customer_name", "Walk-in Customer") \
        .limit(8) \
        .execute()

    # Deduplicate names
    seen = set()
    suggestions = []
    for s in (res.data or []):
        name = s.get("customer_name", "")
        if name and name not in seen:
            seen.add(name)
            suggestions.append(name)

    return {
        "success": True,
        "suggestions": suggestions
    }


# ==========================
# ✅ GET ALL CUSTOMERS
# List of unique customers with stats
# ==========================

@router.get("/")
def get_all_customers(user=Depends(auth_required)):
    """
    Get list of all unique customers with visit count and total spent.
    """
    store_id = user["store_id"]

    sales_res = supabase.table("sales") \
        .select("customer_name, total_amount, sale_timestamp") \
        .eq("store_id", store_id) \
        .neq("customer_name", "Walk-in Customer") \
        .execute()

    # Aggregate by customer name
    customer_map = {}
    for sale in (sales_res.data or []):
        name = sale.get("customer_name", "")
        if not name:
            continue
        if name not in customer_map:
            customer_map[name] = {
                "customer_name": name,
                "total_visits": 0,
                "total_spent": 0.0,
                "last_visit": None
            }
        customer_map[name]["total_visits"] += 1
        customer_map[name]["total_spent"] += float(sale.get("total_amount", 0))

        visit_date = sale.get("sale_timestamp", "")[:10]
        if not customer_map[name]["last_visit"] or \
                visit_date > customer_map[name]["last_visit"]:
            customer_map[name]["last_visit"] = visit_date

    customers = sorted(
        customer_map.values(),
        key=lambda x: x["total_spent"],
        reverse=True
    )

    # Round totals
    for c in customers:
        c["total_spent"] = round(c["total_spent"], 2)

    return {
        "success": True,
        "customers": customers,
        "total_customers": len(customers)
    }


# ==========================
# ✅ BILL NOTES
# Add a note to any sale
# Example: "Home delivery", "Credit approved"
# ==========================

@router.post("/bill-note")
def add_bill_note(payload: BillNoteUpdate, user=Depends(auth_required)):
    """
    Add or update a note on a sale.
    Only admin can add notes.
    """
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can add bill notes"
        )

    # Verify sale belongs to store
    sale_res = supabase.table("sales") \
        .select("sale_id") \
        .eq("sale_id", payload.sale_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not sale_res.data:
        raise HTTPException(status_code=404, detail="Sale not found")

    supabase.table("sales") \
        .update({"note": payload.note.strip()}) \
        .eq("sale_id", payload.sale_id) \
        .execute()

    return {
        "success": True,
        "message": "Note added to bill",
        "sale_id": payload.sale_id,
        "note": payload.note
    }


# ==========================
# ✅ ADD NOTE DURING BILLING
# This is called from POS before completing sale
# Note is saved with the sale directly
# ==========================

@router.get("/{customer_name}/last-items")
def get_customer_last_items(
    customer_name: str,
    user=Depends(auth_required)
):
    """
    Get the last 3 items this customer bought.
    Shown as suggestions when customer is selected in POS.
    Helps cashier quickly suggest what they usually buy.
    """
    store_id = user["store_id"]

    # Get last sale for this customer
    last_sale_res = supabase.table("sales") \
        .select("sale_id") \
        .eq("store_id", store_id) \
        .ilike("customer_name", f"%{customer_name}%") \
        .order("sale_timestamp", desc=True) \
        .limit(1) \
        .execute()

    if not last_sale_res.data:
        return {"success": True, "items": []}

    sale_id = last_sale_res.data[0]["sale_id"]

    items_res = supabase.table("sale_items") \
        .select("product_id, product_name, quantity, price") \
        .eq("sale_id", sale_id) \
        .limit(3) \
        .execute()

    items = []
    for item in (items_res.data or []):
        items.append({
            "product_id": item.get("product_id"),
            "name": item.get("product_name", "Unknown"),
            "quantity": item.get("quantity", 1),
            "price": float(item.get("price", 0))
        })

    return {
        "success": True,
        "customer_name": customer_name,
        "items": items
    }