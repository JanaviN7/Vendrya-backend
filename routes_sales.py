from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from supabase_client import supabase
import uuid
from auth.dependencies import auth_required

router = APIRouter(prefix="/sales", tags=["Sales"])


class SaleItem(BaseModel):
    product_id: str
    quantity: float


class SaleRequest(BaseModel):
    items: list[SaleItem]


# ✅ Create Sale (Authenticated)
@router.post("/create")
def create_sale(request: SaleRequest, user=Depends(auth_required)):
    try:
        store_id = user["store_id"]
        total = 0
        sale_items_data = []
        stock_updates = {}

        # ✅ Validate items
        for item in request.items:
            product = supabase.table("products").select("*") \
                .eq("product_id", item.product_id).eq("store_id", store_id).single().execute()

            if not product.data:
                raise HTTPException(status_code=404, detail=f"Product not found: {item.product_id}")

            product_data = product.data

            if product_data["quantity"] < item.quantity:
                raise HTTPException(status_code=400,
                                    detail=f"Not enough stock for {product_data['name']}")

            item_total = product_data["price"] * item.quantity
            total += item_total

            sale_items_data.append({
                "product_id": item.product_id,
                "quantity": item.quantity,
                "price": product_data["price"],
                "total": item_total
            })

            stock_updates[item.product_id] = product_data["quantity"] - item.quantity

        # ✅ Create sale record
        sale_id = str(uuid.uuid4())
        supabase.table("sales").insert({
            "sale_id": sale_id,
            "store_id": store_id,
            "total_amount": total,
            "sale_timestamp": datetime.utcnow().isoformat()
        }).execute()

        # ✅ Insert items + update stock + inventory log
        for item in sale_items_data:
            item["sale_id"] = sale_id
            item["store_id"] = store_id

            supabase.table("sale_items").insert(item).execute()

            supabase.table("products").update({
                "quantity": stock_updates[item["product_id"]]
            }).eq("product_id", item["product_id"]).eq("store_id", store_id).execute()

            supabase.table("inventory_logs").insert({
                "product_id": item["product_id"],
                "store_id": store_id,
                "change_qty": -item["quantity"],
                "reason": "sale",
                "new_stock": stock_updates[item["product_id"]],
                "previous_stock": stock_updates[item["product_id"]] + item["quantity"]
            }).execute()

        return {
            "message": "Sale completed successfully",
            "sale_id": sale_id,
            "total_amount": total,
            "items": sale_items_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ List My Store Sales (Authenticated)
@router.get("/")
def list_sales(user=Depends(auth_required)):
    store_id = user["store_id"]
    res = supabase.table("sales").select("*") \
        .eq("store_id", store_id).order("sale_timestamp", desc=True).execute()
    return res.data


# ✅ Get Sale Details with Product Info (Authenticated)
@router.get("/{sale_id}")
def get_sale_details(sale_id: str, user=Depends(auth_required)):
    store_id = user["store_id"]

    sale = supabase.table("sales").select("*") \
        .eq("sale_id", sale_id).eq("store_id", store_id).single().execute()

    if not sale.data:
        raise HTTPException(status_code=404, detail="Sale not found")

    items = supabase.table("sale_items").select("*, products(name, barcode)") \
        .eq("sale_id", sale_id).eq("store_id", store_id).execute()

    return {
        "sale": sale.data,
        "items": items.data
    }
