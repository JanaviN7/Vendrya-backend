from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from uuid import uuid4
from datetime import datetime, date, timezone, timedelta

from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/sales", tags=["Sales"])

# IST = UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


# ==========================
# SCHEMAS
# ==========================

class SaleItem(BaseModel):
    product_id: Optional[str] = None
    barcode: Optional[str] = None
    name: Optional[str] = None
    quantity: int
    discount_pct: Optional[float] = 0.0
    price: Optional[float] = None           # ✅ admin override price
    original_price: Optional[float] = None  # ✅ original price before override
    weight_grams: Optional[float] = None    # ✅ for weight-based items
    weight_label: Optional[str] = None      # ✅ "500gm", "1kg" etc
    variant_id: Optional[str] = None        # ✅ for variant tracking
    cart_label: Optional[str] = None        # ✅ display name e.g. "Rice (500gm)"


class PaymentSplit(BaseModel):
    cash: Optional[float] = 0.0
    upi: Optional[float] = 0.0
    card: Optional[float] = 0.0


class SaleCreate(BaseModel):
    items: List[SaleItem]
    payment_mode: str = "cash"
    payment_split: Optional[PaymentSplit] = None
    discount_pct: Optional[float] = 0.0
    discount_amount: Optional[float] = 0.0
    customer_name: Optional[str] = None     # ✅ customer name on bill


# ✅ NEW — Return/Refund schemas
class ReturnItem(BaseModel):
    sale_item_id: Optional[str] = None
    product_id: str
    quantity: int
    reason: Optional[str] = None


class ReturnRequest(BaseModel):
    sale_id: str
    items: List[ReturnItem]
    refund_mode: str = "cash"   # cash | upi | card | store_credit
    reason: Optional[str] = None


# ✅ NEW — Hold Bill schemas
class HoldBillItem(BaseModel):
    product_id: str
    name: str
    price: float
    quantity: int
    line_total: float
    discount_pct: Optional[float] = 0.0
    weight_grams: Optional[float] = None
    weight_label: Optional[str] = None
    cart_label: Optional[str] = None


class HoldBillCreate(BaseModel):
    items: List[HoldBillItem]
    customer_name: Optional[str] = None
    note: Optional[str] = None
    discount_pct: Optional[float] = 0.0
    discount_amount: Optional[float] = 0.0
    subtotal: Optional[float] = 0.0


# ==========================
# HELPERS
# ==========================

def _find_product(store_id: str, item: SaleItem):
    query = supabase.table("products").select("*").eq("store_id", store_id)

    if item.product_id:
        query = query.eq("product_id", item.product_id)
    elif item.barcode:
        query = query.eq("barcode", item.barcode.strip())
    elif item.name:
        query = query.ilike("name", item.name.strip())
    else:
        raise HTTPException(
            status_code=400,
            detail="Each item must contain product_id OR barcode OR name"
        )

    res = query.limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return res.data[0]


# ==========================
# CREATE SALE (CHECKOUT)
# ==========================

@router.post("/create")
def create_sale(request: SaleCreate, user=Depends(auth_required)):
    store_id = user["store_id"]
    staff_id = user["user_id"]
    sale_id = str(uuid4())

    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")

    total_amount = 0.0
    sale_items_data = []

    try:
        for item in request.items:
            if item.quantity <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be > 0")

            product = _find_product(store_id, item)

            # ✅ Use admin override price if provided, else product price
            unit_price = float(item.price) if item.price else float(product["price"])
            original_price = float(item.original_price) if item.original_price else unit_price

            # ✅ For weight-based items, don't check stock in kg units
            # Stock for weight items is tracked separately
            if not item.weight_grams:
                if product["quantity"] < item.quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient stock for {product['name']}"
                    )

            disc = item.discount_pct or 0.0
            line_total = unit_price * item.quantity * (1 - disc / 100)
            total_amount += line_total

            # ✅ Update stock
            if item.weight_grams:
                # Weight-based: deduct in kg equivalent
                kg_deducted = item.weight_grams / 1000
                new_stock = max(0, product["quantity"] - kg_deducted)
            else:
                new_stock = product["quantity"] - item.quantity

            supabase.table("products").update({
                "quantity": new_stock
            }).eq("product_id", product["product_id"]) \
              .eq("store_id", store_id) \
              .execute()

            # ✅ Inventory log
            supabase.table("inventory_logs").insert({
                "product_id": product["product_id"],
                "store_id": store_id,
                "qty_changed": -(item.weight_grams / 1000 if item.weight_grams else item.quantity),
                "action_type": "sale",
                "timestamp": now_ist().isoformat()
            }).execute()

            # ✅ Display name — use cart_label for weight items
            display_name = item.cart_label or product["name"]

            sale_items_data.append({
                "sale_id": sale_id,
                "product_id": product["product_id"],
                "store_id": store_id,
                "product_name": display_name,
                "quantity": item.quantity,
                "price": unit_price,
                "original_price": original_price,
                "discount_pct": disc,
                "total": round(line_total, 2),
                "weight_grams": item.weight_grams,
                "weight_label": item.weight_label,
                "variant_id": item.variant_id,
            })

        # ✅ Apply bill discount
        bill_disc = request.discount_pct or 0.0
        disc_amount = request.discount_amount or 0.0
        final_amount = total_amount - disc_amount

        # ✅ Payment mode label
        payment_mode = request.payment_mode
        if request.payment_split:
            split = request.payment_split
            parts = []
            if (split.cash or 0) > 0:
                parts.append(f"cash:{split.cash:.0f}")
            if (split.upi or 0) > 0:
                parts.append(f"upi:{split.upi:.0f}")
            if (split.card or 0) > 0:
                parts.append(f"card:{split.card:.0f}")
            if parts:
                payment_mode = "split|" + "|".join(parts)

        supabase.table("sales").insert({
            "sale_id": sale_id,
            "store_id": store_id,
            "staff_id": staff_id,
            "payment_mode": payment_mode,
            "total_amount": round(final_amount, 2),
            "discount_pct": bill_disc,
            "discount_amount": round(disc_amount, 2),
            "customer_name": request.customer_name or "Walk-in Customer",
            "sale_timestamp": now_ist().isoformat(),
            "status": "completed"
        }).execute()

        supabase.table("sale_items").insert(sale_items_data).execute()

        return {
            "success": True,
            "sale_id": sale_id,
            "total_amount": round(final_amount, 2)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================
# ✅ RETURN / REFUND
# Admin only — reverses a sale partially or fully
# Adds stock back, creates return record
# ==========================

@router.post("/return")
def create_return(request: ReturnRequest, user=Depends(auth_required)):
    """
    Process a return/refund for a completed sale.
    - Admin only
    - Can return all or some items from a sale
    - Stock is added back automatically
    - Creates a return record linked to original sale
    - Refund can be cash/upi/card/store_credit
    """
    store_id = user["store_id"]

    # ✅ Only admin can process returns
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can process returns"
        )

    # ✅ Verify original sale exists
    sale_res = supabase.table("sales") \
        .select("*") \
        .eq("sale_id", request.sale_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not sale_res.data:
        raise HTTPException(status_code=404, detail="Original sale not found")

    original_sale = sale_res.data

    # ✅ Check if already fully returned
    if original_sale.get("status") == "fully_returned":
        raise HTTPException(
            status_code=400,
            detail="This sale has already been fully returned"
        )

    # ✅ Get original sale items
    sale_items_res = supabase.table("sale_items") \
        .select("*") \
        .eq("sale_id", request.sale_id) \
        .execute()

    sale_items = {item["product_id"]: item for item in (sale_items_res.data or [])}

    return_id = str(uuid4())
    return_items_data = []
    refund_total = 0.0

    for return_item in request.items:
        if return_item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Return quantity must be > 0")

        # ✅ Validate return qty doesn't exceed original qty
        original_item = sale_items.get(return_item.product_id)
        if not original_item:
            raise HTTPException(
                status_code=400,
                detail=f"Product {return_item.product_id} was not in original sale"
            )

        # ✅ Check already returned quantity
        already_returned_res = supabase.table("return_items") \
            .select("quantity") \
            .eq("sale_id", request.sale_id) \
            .eq("product_id", return_item.product_id) \
            .execute()

        already_returned = sum(
            r["quantity"] for r in (already_returned_res.data or [])
        )
        available_to_return = original_item["quantity"] - already_returned

        if return_item.quantity > available_to_return:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot return {return_item.quantity} units. Only {available_to_return} available to return."
            )

        # ✅ Calculate refund amount for this item
        unit_price = float(original_item["price"])
        disc = float(original_item.get("discount_pct", 0))
        item_refund = unit_price * return_item.quantity * (1 - disc / 100)
        refund_total += item_refund

        # ✅ Add stock back
        product_res = supabase.table("products") \
            .select("quantity") \
            .eq("product_id", return_item.product_id) \
            .eq("store_id", store_id) \
            .single() \
            .execute()

        if product_res.data:
            new_qty = product_res.data["quantity"] + return_item.quantity
            supabase.table("products") \
                .update({"quantity": new_qty}) \
                .eq("product_id", return_item.product_id) \
                .eq("store_id", store_id) \
                .execute()

            # ✅ Log stock return in inventory
            supabase.table("inventory_logs").insert({
                "product_id": return_item.product_id,
                "store_id": store_id,
                "qty_changed": return_item.quantity,
                "action_type": "return",
                "timestamp": now_ist().isoformat()
            }).execute()

        return_items_data.append({
            "return_id": return_id,
            "sale_id": request.sale_id,
            "product_id": return_item.product_id,
            "store_id": store_id,
            "quantity": return_item.quantity,
            "refund_amount": round(item_refund, 2),
            "reason": return_item.reason or request.reason,
        })

    # ✅ Create return record
    supabase.table("returns").insert({
        "return_id": return_id,
        "sale_id": request.sale_id,
        "store_id": store_id,
        "processed_by": user["user_id"],
        "refund_total": round(refund_total, 2),
        "refund_mode": request.refund_mode,
        "reason": request.reason,
        "return_timestamp": now_ist().isoformat(),
        "status": "completed"
    }).execute()

    # ✅ Insert return items
    if return_items_data:
        supabase.table("return_items").insert(return_items_data).execute()

    # ✅ Check if sale is now fully returned
    all_returned_res = supabase.table("return_items") \
        .select("quantity") \
        .eq("sale_id", request.sale_id) \
        .execute()

    total_returned = sum(r["quantity"] for r in (all_returned_res.data or []))
    total_original = sum(i["quantity"] for i in sale_items.values())

    new_sale_status = "fully_returned" if total_returned >= total_original else "partially_returned"
    supabase.table("sales") \
        .update({"status": new_sale_status}) \
        .eq("sale_id", request.sale_id) \
        .execute()

    return {
        "success": True,
        "return_id": return_id,
        "sale_id": request.sale_id,
        "refund_total": round(refund_total, 2),
        "refund_mode": request.refund_mode,
        "sale_status": new_sale_status,
        "message": f"Return processed. Refund of Rs {refund_total:.2f} via {request.refund_mode}."
    }


# ==========================
# ✅ GET RETURNS FOR A SALE
# ==========================

@router.get("/{sale_id}/returns")
def get_sale_returns(sale_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    returns_res = supabase.table("returns") \
        .select("*") \
        .eq("sale_id", sale_id) \
        .eq("store_id", store_id) \
        .order("return_timestamp", desc=True) \
        .execute()

    return {
        "success": True,
        "returns": returns_res.data or []
    }


# ==========================
# ✅ LIST ALL RETURNS
# ==========================

@router.get("/returns/all")
def list_all_returns(user=Depends(auth_required)):
    store_id = user["store_id"]

    returns_res = supabase.table("returns") \
        .select("*, return_items(*)") \
        .eq("store_id", store_id) \
        .order("return_timestamp", desc=True) \
        .limit(50) \
        .execute()

    return {
        "success": True,
        "returns": returns_res.data or []
    }


# ==========================
# ✅ HOLD BILL
# Park a bill temporarily, resume later
# Useful for busy counters
# ==========================

@router.post("/hold")
def hold_bill(request: HoldBillCreate, user=Depends(auth_required)):
    """
    Save current cart as a held bill.
    Does NOT deduct stock — bill is just parked.
    Can be resumed anytime.
    Multiple bills can be held at once.
    """
    store_id = user["store_id"]
    hold_id = str(uuid4())

    if not request.items:
        raise HTTPException(status_code=400, detail="No items to hold")

    # ✅ Generate a short hold reference number
    hold_ref = f"HOLD-{hold_id[:6].upper()}"

    supabase.table("held_bills").insert({
        "hold_id": hold_id,
        "hold_ref": hold_ref,
        "store_id": store_id,
        "created_by": user["user_id"],
        "customer_name": request.customer_name,
        "note": request.note,
        "items": [item.dict() for item in request.items],
        "subtotal": request.subtotal,
        "discount_pct": request.discount_pct,
        "discount_amount": request.discount_amount,
        "status": "held",
        "held_at": now_ist().isoformat()
    }).execute()

    return {
        "success": True,
        "hold_id": hold_id,
        "hold_ref": hold_ref,
        "message": f"Bill parked as {hold_ref}. Resume anytime."
    }


# ==========================
# ✅ GET ALL HELD BILLS
# ==========================

@router.get("/hold/list")
def list_held_bills(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = supabase.table("held_bills") \
        .select("*") \
        .eq("store_id", store_id) \
        .eq("status", "held") \
        .order("held_at", desc=True) \
        .execute()

    return {
        "success": True,
        "held_bills": res.data or [],
        "count": len(res.data or [])
    }


# ==========================
# ✅ RESUME HELD BILL
# ==========================

@router.get("/hold/{hold_id}")
def get_held_bill(hold_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    res = supabase.table("held_bills") \
        .select("*") \
        .eq("hold_id", hold_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Held bill not found")

    if res.data.get("status") != "held":
        raise HTTPException(
            status_code=400,
            detail="This bill has already been completed or cancelled"
        )

    return {
        "success": True,
        "held_bill": res.data
    }


# ==========================
# ✅ COMPLETE HELD BILL
# Mark as completed after sale is created
# ==========================

@router.patch("/hold/{hold_id}/complete")
def complete_held_bill(hold_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    res = supabase.table("held_bills") \
        .select("hold_id, status") \
        .eq("hold_id", hold_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Held bill not found")

    supabase.table("held_bills") \
        .update({
            "status": "completed",
            "completed_at": now_ist().isoformat()
        }) \
        .eq("hold_id", hold_id) \
        .execute()

    return {"success": True, "message": "Held bill marked as completed"}


# ==========================
# ✅ CANCEL HELD BILL
# ==========================

@router.patch("/hold/{hold_id}/cancel")
def cancel_held_bill(hold_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    supabase.table("held_bills") \
        .update({
            "status": "cancelled",
            "completed_at": now_ist().isoformat()
        }) \
        .eq("hold_id", hold_id) \
        .eq("store_id", store_id) \
        .execute()

    return {"success": True, "message": "Held bill cancelled"}


# ==========================
# TODAY SUMMARY
# ==========================

@router.get("/today/summary")
def today_sales(user=Depends(auth_required)):
    store_id = user["store_id"]
    today = today_ist().isoformat()

    try:
        sales_res = supabase.table("sales") \
            .select("sale_id,total_amount") \
            .eq("store_id", store_id) \
            .gte("sale_timestamp", f"{today}T00:00:00") \
            .lte("sale_timestamp", f"{today}T23:59:59") \
            .execute()

        sales = sales_res.data or []
        total_sales = sum(float(s["total_amount"]) for s in sales)
        total_orders = len(sales)
        sale_ids = [s["sale_id"] for s in sales]

        total_items_sold = 0
        if sale_ids:
            items_res = supabase.table("sale_items") \
                .select("quantity") \
                .in_("sale_id", sale_ids) \
                .execute()
            total_items_sold = sum(int(i["quantity"]) for i in (items_res.data or []))

        # ✅ Also show today's returns
        returns_res = supabase.table("returns") \
            .select("refund_total") \
            .eq("store_id", store_id) \
            .gte("return_timestamp", f"{today}T00:00:00") \
            .lte("return_timestamp", f"{today}T23:59:59") \
            .execute()

        total_refunds = sum(
            float(r["refund_total"]) for r in (returns_res.data or [])
        )

        return {
            "success": True,
            "date": today,
            "total_sales_amount": total_sales,
            "total_orders": total_orders,
            "total_items_sold": total_items_sold,
            "total_refunds": total_refunds,
            "net_sales": round(total_sales - total_refunds, 2)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================
# LIST SALES
# ==========================

@router.get("/")
def list_sales(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = supabase.table("sales") \
        .select("*") \
        .eq("store_id", store_id) \
        .order("sale_timestamp", desc=True) \
        .execute()

    return {
        "success": True,
        "data": res.data or []
    }


# ==========================
# SALE DETAILS
# ==========================

@router.get("/{sale_id}")
def sale_details(sale_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    sale = supabase.table("sales") \
        .select("*") \
        .eq("sale_id", sale_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not sale.data:
        raise HTTPException(status_code=404, detail="Sale not found")

    items = supabase.table("sale_items") \
        .select("quantity, price, original_price, discount_pct, total, product_name, weight_label, products(name, barcode)") \
        .eq("sale_id", sale_id) \
        .execute()

    # ✅ Get returns for this sale
    returns = supabase.table("returns") \
        .select("*") \
        .eq("sale_id", sale_id) \
        .execute()

    return {
        "success": True,
        "sale": sale.data,
        "items": items.data or [],
        "returns": returns.data or []
    }