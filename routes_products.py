from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from supabase_client import supabase
from auth.dependencies import auth_required
from config import DEFAULT_STORE_CATEGORIES
from routes_subscription import check_plan_limit, DEMO_STORE_IDS

router = APIRouter(prefix="/products", tags=["Products"])


# =====================
# MODELS
# =====================

class ProductVariant(BaseModel):
    name: str           # "100g", "200g", "500g", "1kg", "custom"
    price: float
    quantity: int = 0
    barcode: str | None = None


class ProductIn(BaseModel):
    name: str
    category: str | None = None
    quantity: int = 0
    price: float                        # base price (per unit / per kg)
    barcode: str | None = None
    threshold_qty: int = 5
    cost_price: float | None = None     # for profit margin
    has_variants: bool = False          # ✅ NEW — grocery/loose items
    unit: str | None = "unit"           # "kg", "gm", "litre", "unit"
    variants: List[ProductVariant] = [] # ✅ NEW — list of variants


class StockUpdate(BaseModel):
    quantity: int


class PriceUpdate(BaseModel):
    price: float


class VariantIn(BaseModel):
    product_id: str
    name: str
    price: float
    quantity: int = 0
    barcode: str | None = None


class VariantUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    quantity: int | None = None


# =====================
# CREATE PRODUCT
# =====================

@router.post("/")
def add_product(product: ProductIn, user=Depends(auth_required)):
    store_id = user["store_id"]

    if store_id not in DEMO_STORE_IDS:
        check_plan_limit(store_id, "products")

    data = product.dict(exclude={"variants"})
    data["store_id"] = store_id

    result = supabase.table("products").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to add product")

    product_id = result.data[0]["product_id"]

    # ✅ Insert variants if provided
    if product.has_variants and product.variants:
        for v in product.variants:
            supabase.table("product_variants").insert({
                "product_id": product_id,
                "store_id": store_id,
                "name": v.name,
                "price": v.price,
                "quantity": v.quantity,
                "barcode": v.barcode,
            }).execute()

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

    products = result.data or []

    # ✅ Attach variants to products that have them
    for p in products:
        if p.get("has_variants"):
            variants_res = (
                supabase.table("product_variants")
                .select("*")
                .eq("product_id", p["product_id"])
                .execute()
            )
            p["variants"] = variants_res.data or []
        else:
            p["variants"] = []

    return {
        "success": True,
        "data": products
    }


# =====================
# UPDATE PRODUCT STOCK
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

    return {"success": True, "new_quantity": new_qty}


# =====================
# ✅ UPDATE PRODUCT PRICE (Admin only)
# Allows admin to update base price anytime
# Also logs the price change for price history chart
# =====================

@router.put("/{product_id}/price")
def update_price(
    product_id: str,
    data: PriceUpdate,
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    # ✅ Only admin can change price
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can update prices")

    res = (
        supabase.table("products")
        .select("price, name")
        .eq("product_id", product_id)
        .eq("store_id", store_id)
        .single()
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    old_price = res.data["price"]

    # Update price
    supabase.table("products") \
        .update({"price": data.price}) \
        .eq("product_id", product_id) \
        .eq("store_id", store_id) \
        .execute()

    # ✅ Log price change for history chart
    supabase.table("price_history").insert({
        "product_id": product_id,
        "store_id": store_id,
        "old_price": old_price,
        "new_price": data.price,
        "changed_by": user.get("user_id"),
        "changed_at": __import__("datetime").datetime.utcnow().isoformat()
    }).execute()

    return {
        "success": True,
        "product_id": product_id,
        "old_price": old_price,
        "new_price": data.price
    }


# =====================
# ✅ GET PRICE HISTORY (for line chart)
# =====================

@router.get("/{product_id}/price-history")
def get_price_history(product_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("price_history")
        .select("*")
        .eq("product_id", product_id)
        .eq("store_id", store_id)
        .order("changed_at", desc=False)
        .execute()
    )

    return {
        "success": True,
        "data": res.data or []
    }


# =====================
# ✅ VARIANTS — ADD
# =====================

@router.post("/variants")
def add_variant(variant: VariantIn, user=Depends(auth_required)):
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can add variants")

    # Check product belongs to store
    res = supabase.table("products") \
        .select("product_id") \
        .eq("product_id", variant.product_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    result = supabase.table("product_variants").insert({
        "product_id": variant.product_id,
        "store_id": store_id,
        "name": variant.name,
        "price": variant.price,
        "quantity": variant.quantity,
        "barcode": variant.barcode,
    }).execute()

    # Mark product as has_variants
    supabase.table("products") \
        .update({"has_variants": True}) \
        .eq("product_id", variant.product_id) \
        .execute()

    return {"success": True, "variant": result.data[0]}


# =====================
# ✅ VARIANTS — LIST
# =====================

@router.get("/{product_id}/variants")
def list_variants(product_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("product_variants")
        .select("*")
        .eq("product_id", product_id)
        .eq("store_id", store_id)
        .execute()
    )

    return {"success": True, "data": res.data or []}


# =====================
# ✅ VARIANTS — UPDATE
# =====================

@router.put("/variants/{variant_id}")
def update_variant(
    variant_id: str,
    data: VariantUpdate,
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can update variants")

    update_data = {k: v for k, v in data.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")

    supabase.table("product_variants") \
        .update(update_data) \
        .eq("variant_id", variant_id) \
        .eq("store_id", store_id) \
        .execute()

    return {"success": True}


# =====================
# ✅ VARIANTS — DELETE
# =====================

@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete variants")

    supabase.table("product_variants") \
        .delete() \
        .eq("variant_id", variant_id) \
        .eq("store_id", store_id) \
        .execute()

    return {"success": True}


# =====================
# ✅ BULK PRICE UPDATE
# Update all products in a category by %
# Example: Oil prices up 5% → update all oil products
# =====================

class BulkPriceUpdate(BaseModel):
    category: str
    change_percent: float   # positive = increase, negative = decrease


@router.post("/bulk-price-update")
def bulk_price_update(data: BulkPriceUpdate, user=Depends(auth_required)):
    store_id = user["store_id"]

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can bulk update prices")

    # Get all products in category
    res = supabase.table("products") \
        .select("product_id, price, name") \
        .eq("store_id", store_id) \
        .eq("category", data.category) \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="No products found in this category")

    updated = []
    for product in res.data:
        old_price = product["price"]
        new_price = round(old_price * (1 + data.change_percent / 100), 2)

        supabase.table("products") \
            .update({"price": new_price}) \
            .eq("product_id", product["product_id"]) \
            .execute()

        # Log price change
        supabase.table("price_history").insert({
            "product_id": product["product_id"],
            "store_id": store_id,
            "old_price": old_price,
            "new_price": new_price,
            "changed_by": user.get("user_id"),
            "changed_at": __import__("datetime").datetime.utcnow().isoformat()
        }).execute()

        updated.append({
            "product_id": product["product_id"],
            "name": product["name"],
            "old_price": old_price,
            "new_price": new_price
        })

    return {
        "success": True,
        "updated_count": len(updated),
        "updated": updated
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
    return {"success": True, "data": res.data or []}


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
    return {"success": True, "data": res.data or []}


# =====================
# SCAN BARCODE
# =====================

@router.get("/scan/{barcode}")
def scan_barcode(barcode: str, user=Depends(auth_required)):
    store_id = user["store_id"]
    clean_barcode = barcode.strip()

    # Check main products
    res = (
        supabase.table("products")
        .select("*")
        .eq("store_id", store_id)
        .eq("barcode", clean_barcode)
        .execute()
    )

    if res.data:
        product = res.data[0]
        # Attach variants if any
        if product.get("has_variants"):
            variants_res = supabase.table("product_variants") \
                .select("*") \
                .eq("product_id", product["product_id"]) \
                .execute()
            product["variants"] = variants_res.data or []
        return {"success": True, "found": True, "product": product}

    # Check variant barcodes
    variant_res = (
        supabase.table("product_variants")
        .select("*, products(*)")
        .eq("store_id", store_id)
        .eq("barcode", clean_barcode)
        .execute()
    )

    if variant_res.data:
        v = variant_res.data[0]
        return {
            "success": True,
            "found": True,
            "product": v.get("products"),
            "matched_variant": {
                "variant_id": v["variant_id"],
                "name": v["name"],
                "price": v["price"],
                "quantity": v["quantity"],
            }
        }

    return {"success": True, "found": False, "message": "Product not registered"}


# =====================
# DEFAULT CATEGORIES
# =====================

@router.get("/categories/default")
def get_default_categories():
    return {"success": True, "data": DEFAULT_STORE_CATEGORIES}


# =====================
# ✅ WEIGHT-BASED PRICE CALCULATION
# For loose/grocery items sold by weight
# Example: Rice ₹60/kg → 500gm = ₹30
# =====================

class WeightPriceRequest(BaseModel):
    product_id: str
    weight_grams: float       # weight customer wants in grams
    override_price: float | None = None  # admin can override base price


class WeightPriceResponse(BaseModel):
    product_id: str
    product_name: str
    base_price_per_kg: float
    weight_grams: float
    weight_label: str         # "500gm", "1kg", "250gm" etc
    calculated_price: float
    cart_label: str           # "Rice (500gm)"


@router.post("/calculate-weight-price")
def calculate_weight_price(
    data: WeightPriceRequest,
    user=Depends(auth_required)
):
    """
    Calculate price for a loose/weight-based product.
    Base price is always stored as price per KG.
    Frontend sends weight in grams, we return calculated price.
    Admin can override base price before calculating.
    """
    store_id = user["store_id"]

    # Get product
    res = supabase.table("products") \
        .select("product_id, name, price, unit, category") \
        .eq("product_id", data.product_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = res.data

    # Use override price if admin provided one, else use stored price
    base_price_per_kg = data.override_price if data.override_price else product["price"]

    # Calculate price based on weight
    # Formula: (weight_grams / 1000) * price_per_kg
    weight_kg = data.weight_grams / 1000
    calculated_price = round(weight_kg * base_price_per_kg, 2)

    # Generate human-readable weight label
    if data.weight_grams >= 1000:
        kg = data.weight_grams / 1000
        weight_label = f"{kg:.1f}kg" if kg != int(kg) else f"{int(kg)}kg"
    else:
        weight_label = f"{int(data.weight_grams)}gm"

    cart_label = f"{product['name']} ({weight_label})"

    return {
        "success": True,
        "product_id": product["product_id"],
        "product_name": product["name"],
        "base_price_per_kg": base_price_per_kg,
        "weight_grams": data.weight_grams,
        "weight_label": weight_label,
        "calculated_price": calculated_price,
        "cart_label": cart_label,
    }


# =====================
# ✅ GET COMMON WEIGHT OPTIONS
# Returns standard weight options for a product
# Frontend uses this to show quick-select buttons
# =====================

@router.get("/{product_id}/weight-options")
def get_weight_options(product_id: str, user=Depends(auth_required)):
    """
    Returns quick weight options for a product
    along with pre-calculated prices for each.
    """
    store_id = user["store_id"]

    res = supabase.table("products") \
        .select("product_id, name, price, unit") \
        .eq("product_id", product_id) \
        .eq("store_id", store_id) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = res.data
    base_price = product["price"]

    # Standard weight options in grams
    standard_weights = [100, 200, 250, 500, 750, 1000, 2000, 5000]
    weight_options = []

    for grams in standard_weights:
        price = round((grams / 1000) * base_price, 2)
        if grams >= 1000:
            kg = grams / 1000
            label = f"{int(kg)}kg" if kg == int(kg) else f"{kg}kg"
        else:
            label = f"{grams}gm"

        weight_options.append({
            "grams": grams,
            "label": label,
            "price": price,
            "cart_label": f"{product['name']} ({label})"
        })

    return {
        "success": True,
        "product_id": product_id,
        "product_name": product["name"],
        "base_price_per_kg": base_price,
        "unit": product.get("unit", "kg"),
        "weight_options": weight_options
    }