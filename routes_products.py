from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from supabase_client import supabase
from auth.dependencies import auth_required
from config import DEFAULT_STORE_CATEGORIES

router = APIRouter(prefix="/products", tags=["Products"])


# =====================
# MODELS
# =====================
class ProductIn(BaseModel):
    name: str
    category: str | None = None
    quantity: int = 0
    price: float
    barcode: str | None = None
    threshold_qty: int = 5


class StockUpdate(BaseModel):
    quantity: int


# =====================
# CREATE PRODUCT
# =====================
@router.post("/")
def add_product(product: ProductIn, user=Depends(auth_required)):
    store_id = user["store_id"]

    data = product.dict()
    data["store_id"] = store_id

    result = supabase.table("products").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to add product")

    return {
        "success": True,
        "product": result.data[0]
    }


# =====================
# LIST PRODUCTS
# =====================
@router.get("/")
def list_products(user=Depends(auth_required)):
    store_id = user["store_id"]

    result = (
        supabase.table("products")
        .select("*")
        .eq("store_id", store_id)
        .execute()
    )

    return {
        "success": True,
        "data": result.data or []
    }


# =====================
# UPDATE STOCK
# =====================
@router.put("/{product_id}")
def update_stock(
    product_id: str,
    data: StockUpdate,
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    res = (
        supabase.table("products")
        .select("quantity")
        .eq("product_id", product_id)
        .eq("store_id", store_id)
        .single()
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    new_qty = res.data["quantity"] + data.quantity

    if new_qty < 0:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    supabase.table("products") \
        .update({"quantity": new_qty}) \
        .eq("product_id", product_id) \
        .eq("store_id", store_id) \
        .execute()

    supabase.table("inventory_logs").insert({
        "product_id": product_id,
        "store_id": store_id,
        "qty_changed": data.quantity,
        "action_type": "add" if data.quantity > 0 else "remove"
    }).execute()

    return {
        "success": True,
        "new_quantity": new_qty
    }


# =====================
# SEARCH PRODUCTS
# =====================
@router.get("/search")
def search_products(
    q: str | None = Query(None),
    barcode: str | None = Query(None),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    query = supabase.table("products").select("*").eq("store_id", store_id)

    if barcode:
        query = query.eq("barcode", barcode.strip())
    elif q:
        query = query.ilike("name", f"%{q}%")

    res = query.limit(20).execute()

    return {
        "success": True,
        "data": res.data or []
    }


# =====================
# LOW STOCK
# =====================
@router.get("/low-stock")
def low_stock(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("low_stock_products")
        .select("*")
        .eq("store_id", store_id)
        .order("quantity")
        .execute()
    )

    return {
        "success": True,
        "data": res.data or []
    }


# =====================
# SCAN BARCODE
# =====================
@router.get("/scan/{barcode}")
def scan_barcode(barcode: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    clean_barcode = barcode.strip()  # 🔥 FIX

    res = (
        supabase.table("products")
        .select("*")
        .eq("store_id", store_id)
        .eq("barcode", clean_barcode)
        .execute()
    )

    if res.data:
        return {
            "success": True,
            "found": True,
            "product": res.data[0]
        }

    return {
        "success": True,
        "found": False,
        "message": "Product not registered"
    }


# =====================
# DEFAULT CATEGORIES
# =====================
@router.get("/categories/default")
def get_default_categories():
    return {
        "success": True,
        "data": DEFAULT_STORE_CATEGORIES
    }
