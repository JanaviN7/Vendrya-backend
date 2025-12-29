from fastapi import APIRouter, HTTPException
from supabase_client import supabase

router = APIRouter(prefix="/inventory", tags=["Inventory Logs"])


# ✅ Get full inventory log history
@router.get("/logs")
def get_inventory_logs():
    try:
        res = (
            supabase.table("inventory_logs")
            .select("*, products(name, barcode)")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ Get inventory logs for a specific product
@router.get("/logs/{product_id}")
def get_product_logs(product_id: str):
    try:
        res = (
            supabase.table("inventory_logs")
            .select("*, products(name, barcode)")
            .eq("product_id", product_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
