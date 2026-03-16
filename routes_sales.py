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
    discount_pct: Optional[float] = 0.0   # ✅ per-item discount %


class PaymentSplit(BaseModel):
    cash: Optional[float] = 0.0
    upi: Optional[float] = 0.0
    card: Optional[float] = 0.0


class SaleCreate(BaseModel):
    items: List[SaleItem]
    payment_mode: str = "cash"
    payment_split: Optional[PaymentSplit] = None   # ✅ split payment
    discount_pct: Optional[float] = 0.0            # ✅ total bill discount %
    discount_amount: Optional[float] = 0.0


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

            if product["quantity"] < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {product['name']}"
                )

            # ✅ Apply per-item discount
            disc = item.discount_pct or 0.0
            unit_price = float(product["price"])
            line_total = unit_price * item.quantity * (1 - disc / 100)
            total_amount += line_total
            new_stock = product["quantity"] - item.quantity

            # Update stock
            supabase.table("products").update({
                "quantity": new_stock
            }).eq("product_id", product["product_id"]) \
             .eq("store_id", store_id) \
             .execute()

            # IST timestamp in inventory log
            supabase.table("inventory_logs").insert({
                "product_id": product["product_id"],
                "store_id": store_id,
                "qty_changed": -item.quantity,
                "action_type": "sale",
                "timestamp": now_ist().isoformat()
            }).execute()

            sale_items_data.append({
                "sale_id": sale_id,
                "product_id": product["product_id"],
                "store_id": store_id,
                "quantity": item.quantity,
                "price": unit_price,
                "discount_pct": disc,
                "total": round(line_total, 2)
            })

        # ✅ Apply total bill discount
        bill_disc = request.discount_pct or 0.0
        disc_amount = request.discount_amount or 0.0
        final_amount = total_amount - disc_amount

        # ✅ Determine payment mode label
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

        # IST timestamp in sale
        supabase.table("sales").insert({
            "sale_id": sale_id,
            "store_id": store_id,
            "staff_id": staff_id,
            "payment_mode": payment_mode,
            "total_amount": round(final_amount, 2),
            "discount_pct": bill_disc,
            "discount_amount": round(disc_amount, 2),
            "sale_timestamp": now_ist().isoformat()
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
# TODAY SUMMARY
# ✅ Uses IST date so dashboard shows correct today's sales
# ==========================

@router.get("/today/summary")
def today_sales(user=Depends(auth_required)):
    store_id = user["store_id"]
    today = today_ist().isoformat()

    try:
        sales_res = (
            supabase.table("sales")
            .select("sale_id,total_amount")
            .eq("store_id", store_id)
            .gte("sale_timestamp", f"{today}T00:00:00")
            .lte("sale_timestamp", f"{today}T23:59:59")
            .execute()
        )

        sales = sales_res.data or []
        total_sales = sum(float(s["total_amount"]) for s in sales)
        total_orders = len(sales)
        sale_ids = [s["sale_id"] for s in sales]

        total_items_sold = 0
        if sale_ids:
            items_res = (
                supabase.table("sale_items")
                .select("quantity")
                .in_("sale_id", sale_ids)
                .execute()
            )
            total_items_sold = sum(int(i["quantity"]) for i in (items_res.data or []))

        return {
            "success": True,
            "date": today,
            "total_sales_amount": total_sales,
            "total_orders": total_orders,
            "total_items_sold": total_items_sold
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================
# LIST SALES
# ==========================

@router.get("/")
def list_sales(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("sales")
        .select("*")
        .eq("store_id", store_id)
        .order("sale_timestamp", desc=True)
        .execute()
    )

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

    sale = (
        supabase.table("sales")
        .select("*")
        .eq("sale_id", sale_id)
        .eq("store_id", store_id)
        .single()
        .execute()
    )

    if not sale.data:
        raise HTTPException(status_code=404, detail="Sale not found")

    items = (
        supabase.table("sale_items")
        .select("quantity, price, discount_pct, total, products(name, barcode)")
        .eq("sale_id", sale_id)
        .execute()
    )

    return {
        "success": True,
        "sale": sale.data,
        "items": items.data or []
    }