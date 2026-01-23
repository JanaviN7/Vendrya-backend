from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4
from datetime import datetime, date

from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/sales", tags=["Sales"])


# ==========================
# SCHEMAS
# ==========================

class SaleItem(BaseModel):
    """
    IMPORTANT:
    Vendor NEVER knows product_id.
    UI will fetch product by barcode scan OR search by name,
    then internally store product_id inside cart.

    Checkout should send product_id.
    We still keep barcode/name for backward compatibility.
    """
    product_id: Optional[str] = None
    barcode: Optional[str] = None
    name: Optional[str] = None
    quantity: int


class SaleCreate(BaseModel):
    items: List[SaleItem]
    payment_mode: str = "cash"


# ==========================
# HELPERS
# ==========================

def _find_product(store_id: str, item: SaleItem):
    """
    Fetch product using product_id (preferred),
    otherwise barcode or name (fallback).
    """
    query = supabase.table("products").select("*").eq("store_id", store_id)

    if item.product_id:
        query = query.eq("product_id", item.product_id)

    elif item.barcode:
        query = query.eq("barcode", item.barcode.strip())

    elif item.name:
        # Use case-insensitive exact match
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


def _ensure_sales_columns_exist_example_note():
    """
    NOTE (not executed):
    Sales insert uses staff_id + payment_mode.
    Ensure your sales table has these columns.
    """
    pass


# ==========================
# CREATE SALE (CHECKOUT)
# ==========================

@router.post("/create")
def create_sale(request: SaleCreate, user=Depends(auth_required)):
    store_id = user["store_id"]
    staff_id = user["user_id"]  # cashier/admin token user
    sale_id = str(uuid4())

    if not request.items:
        raise HTTPException(status_code=400, detail="No items provided")

    total_amount = 0.0
    sale_items_data = []

    try:
        # ------------------
        # PROCESS ITEMS
        # ------------------
        for item in request.items:
            if item.quantity <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be > 0")

            product = _find_product(store_id, item)

            # stock check
            if product["quantity"] < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {product['name']}"
                )

            line_total = float(product["price"]) * item.quantity
            total_amount += line_total

            new_stock = product["quantity"] - item.quantity

            # ------------------
            # UPDATE PRODUCT STOCK
            # ------------------
            supabase.table("products").update({
                "quantity": new_stock
            }).eq("product_id", product["product_id"]) \
             .eq("store_id", store_id) \
             .execute()

            # ------------------
            # INVENTORY LOG
            # ------------------
            supabase.table("inventory_logs").insert({
                "product_id": product["product_id"],
                "store_id": store_id,
                "qty_changed": -item.quantity,
                "action_type": "sale",
                "timestamp": datetime.utcnow().isoformat()
            }).execute()

            # ------------------
            # SALE ITEM ROW
            # ------------------
            sale_items_data.append({
                "sale_id": sale_id,
                "product_id": product["product_id"],
                "store_id": store_id,
                "quantity": item.quantity,
                "price": product["price"],
                "total": line_total
            })

        # ------------------
        # INSERT SALE HEADER
        # ------------------
        # ✅ includes staff_id for staff-wise reports
        # ✅ includes payment_mode
        supabase.table("sales").insert({
            "sale_id": sale_id,
            "store_id": store_id,
            "staff_id": staff_id,
            "payment_mode": request.payment_mode,
            "total_amount": total_amount,
            "sale_timestamp": datetime.utcnow().isoformat()
        }).execute()

        # ------------------
        # INSERT SALE ITEMS
        # ------------------
        supabase.table("sale_items").insert(sale_items_data).execute()

        return {
            "success": True,
            "sale_id": sale_id,
            "total_amount": total_amount
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================
# TODAY SUMMARY  ✅ MUST be above /{sale_id}
# ==========================

@router.get("/today/summary")
def today_sales(user=Depends(auth_required)):
    store_id = user["store_id"]
    today = date.today().isoformat()

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
        .select("quantity, price, total, products(name, barcode)")
        .eq("sale_id", sale_id)
        .execute()
    )

    return {
        "success": True,
        "sale": sale.data,
        "items": items.data or []
    }
