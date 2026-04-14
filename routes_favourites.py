from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime, timezone

router = APIRouter(prefix="/favourites", tags=["Favourites"])


# ==========================
# SCHEMAS
# ==========================

class FavouriteItem(BaseModel):
    product_id: str
    name: str
    price: float
    unit: Optional[str] = "unit"
    has_variants: Optional[bool] = False


class FavouriteCreate(BaseModel):
    product_id: str
    display_order: Optional[int] = 0


class FavouriteUpdate(BaseModel):
    display_order: int


# ==========================
# ✅ GET FAVOURITES
# Returns quick-access products for POS screen
# ==========================

@router.get("/")
def get_favourites(user=Depends(auth_required)):
    """
    Get all favourite products for this store.
    These appear as quick-tap buttons at top of POS screen.
    """
    store_id = user["store_id"]

    res = supabase.table("favourites") \
        .select("favourite_id, product_id, display_order, products(*)") \
        .eq("store_id", store_id) \
        .order("display_order") \
        .execute()

    favourites = []
    for f in (res.data or []):
        product = f.get("products")
        if product:
            favourites.append({
                "favourite_id": f["favourite_id"],
                "product_id": f["product_id"],
                "display_order": f["display_order"],
                "name": product.get("name"),
                "price": product.get("price"),
                "quantity": product.get("quantity"),
                "unit": product.get("unit", "unit"),
                "has_variants": product.get("has_variants", False),
                "category": product.get("category"),
                "barcode": product.get("barcode"),
            })

    return {
        "success": True,
        "favourites": favourites,
        "count": len(favourites)
    }


# ==========================
# ✅ ADD TO FAVOURITES
# ==========================

@router.post("/")
def add_favourite(payload: FavouriteCreate, user=Depends(auth_required)):
    """Add a product to quick bill favourites."""
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can manage favourites"
        )

    # Check product belongs to this store
    product_res = supabase.table("products") \
        .select("product_id, name") \
        .eq("product_id", payload.product_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not product_res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if already a favourite
    existing = supabase.table("favourites") \
        .select("favourite_id") \
        .eq("product_id", payload.product_id) \
        .eq("store_id", store_id) \
        .execute()

    if existing.data:
        raise HTTPException(
            status_code=400,
            detail="Product is already in favourites"
        )

    # ✅ Max 12 favourites (fits nicely on mobile screen)
    count_res = supabase.table("favourites") \
        .select("favourite_id", count="exact") \
        .eq("store_id", store_id) \
        .execute()

    if (count_res.count or 0) >= 12:
        raise HTTPException(
            status_code=400,
            detail="Maximum 12 favourites allowed. Remove one to add another."
        )

    result = supabase.table("favourites").insert({
        "store_id": store_id,
        "product_id": payload.product_id,
        "display_order": payload.display_order,
        "added_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    return {
        "success": True,
        "message": f"{product_res.data['name']} added to favourites!",
        "favourite": result.data[0] if result.data else None
    }


# ==========================
# ✅ REMOVE FROM FAVOURITES
# ==========================

@router.delete("/{favourite_id}")
def remove_favourite(favourite_id: str, user=Depends(auth_required)):
    """Remove a product from quick bill favourites."""
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can manage favourites"
        )

    supabase.table("favourites") \
        .delete() \
        .eq("favourite_id", favourite_id) \
        .eq("store_id", store_id) \
        .execute()

    return {"success": True, "message": "Removed from favourites"}


# ==========================
# ✅ REORDER FAVOURITES
# ==========================

@router.patch("/{favourite_id}/order")
def update_favourite_order(
    favourite_id: str,
    payload: FavouriteUpdate,
    user=Depends(auth_required)
):
    """Update display order of a favourite (for drag-to-reorder)."""
    store_id = user["store_id"]

    supabase.table("favourites") \
        .update({"display_order": payload.display_order}) \
        .eq("favourite_id", favourite_id) \
        .eq("store_id", store_id) \
        .execute()

    return {"success": True}


# ==========================
# ✅ REPEAT LAST SALE
# Returns items from the most recent completed sale
# so cashier can recreate it with one tap
# ==========================

@router.get("/repeat-last-sale")
def repeat_last_sale(user=Depends(auth_required)):
    """
    Get items from the last completed sale for this store.
    Cashier can load these into cart with one tap.
    Useful for regular customers who buy same items daily.
    """
    store_id = user["store_id"]

    # Get last completed sale
    last_sale_res = supabase.table("sales") \
        .select("sale_id, total_amount, customer_name, payment_mode, sale_timestamp") \
        .eq("store_id", store_id) \
        .eq("status", "completed") \
        .order("sale_timestamp", desc=True) \
        .limit(1) \
        .execute()

    if not last_sale_res.data:
        return {
            "success": False,
            "message": "No previous sales found"
        }

    last_sale = last_sale_res.data[0]
    sale_id = last_sale["sale_id"]

    # Get items from that sale
    items_res = supabase.table("sale_items") \
        .select("product_id, product_name, quantity, price, discount_pct, weight_grams, weight_label, products(name, price, quantity, unit, has_variants, barcode)") \
        .eq("sale_id", sale_id) \
        .execute()

    cart_items = []
    for item in (items_res.data or []):
        product = item.get("products") or {}

        # ✅ Check current stock availability
        current_qty = int(product.get("quantity", 0))
        requested_qty = int(item.get("quantity", 1))
        available = current_qty >= requested_qty

        cart_items.append({
            "product_id": item["product_id"],
            "name": item.get("product_name") or product.get("name", "Unknown"),
            "price": float(item.get("price", 0)),
            "quantity": requested_qty,
            "line_total": float(item.get("price", 0)) * requested_qty,
            "discount_pct": float(item.get("discount_pct", 0)),
            "weight_grams": item.get("weight_grams"),
            "weight_label": item.get("weight_label"),
            "unit": product.get("unit", "unit"),
            "has_variants": product.get("has_variants", False),
            "barcode": product.get("barcode"),
            "current_stock": current_qty,
            "available": available,  # ✅ warn if out of stock
        })

    return {
        "success": True,
        "last_sale": {
            "sale_id": sale_id,
            "customer_name": last_sale.get("customer_name", "Walk-in"),
            "total_amount": last_sale.get("total_amount"),
            "sale_timestamp": last_sale.get("sale_timestamp"),
        },
        "items": cart_items,
        "items_count": len(cart_items)
    }


# ==========================
# ✅ REPEAT SPECIFIC SALE
# Load any past sale into cart by sale_id
# ==========================

@router.get("/repeat-sale/{sale_id}")
def repeat_specific_sale(sale_id: str, user=Depends(auth_required)):
    """
    Load a specific past sale into cart.
    Admin can pick any sale from history to repeat.
    """
    store_id = user["store_id"]

    sale_res = supabase.table("sales") \
        .select("sale_id, total_amount, customer_name, sale_timestamp") \
        .eq("sale_id", sale_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not sale_res.data:
        raise HTTPException(status_code=404, detail="Sale not found")

    items_res = supabase.table("sale_items") \
        .select("product_id, product_name, quantity, price, discount_pct, weight_grams, weight_label, products(name, price, quantity, unit, has_variants, barcode)") \
        .eq("sale_id", sale_id) \
        .execute()

    cart_items = []
    for item in (items_res.data or []):
        product = item.get("products") or {}
        current_qty = int(product.get("quantity", 0))
        requested_qty = int(item.get("quantity", 1))

        cart_items.append({
            "product_id": item["product_id"],
            "name": item.get("product_name") or product.get("name", "Unknown"),
            "price": float(item.get("price", 0)),
            "quantity": requested_qty,
            "line_total": float(item.get("price", 0)) * requested_qty,
            "discount_pct": float(item.get("discount_pct", 0)),
            "weight_grams": item.get("weight_grams"),
            "weight_label": item.get("weight_label"),
            "unit": product.get("unit", "unit"),
            "has_variants": product.get("has_variants", False),
            "barcode": product.get("barcode"),
            "current_stock": current_qty,
            "available": current_qty >= requested_qty,
        })

    return {
        "success": True,
        "sale": sale_res.data,
        "items": cart_items
    }