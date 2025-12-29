from fastapi import APIRouter, HTTPException, Depends
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime

router = APIRouter(prefix="/reports", tags=["Reports"])


# ✅ Daily Report for Logged-in Store
@router.get("/daily")
def daily_report(user=Depends(auth_required)):
    try:
        store_id = user["store_id"]
        today = datetime.utcnow().date().isoformat()

        result = (
            supabase.table("daily_sales_report")
            .select("*")
            .eq("store_id", store_id)
            .eq("date", today)
            .execute()
        )

        total_revenue = sum(row["revenue"] for row in result.data)

        return {
            "date": today,
            "total_revenue": total_revenue,
            "details": result.data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ Monthly Revenue for Logged-in Store
@router.get("/monthly")
def monthly_report(user=Depends(auth_required)):
    try:
        store_id = user["store_id"]

        result = (
            supabase.table("monthly_sales_report")
            .select("*")
            .eq("store_id", store_id)
            .execute()
        )
        return result.data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ Overall Top Selling Products for Logged-in Store
@router.get("/top-products")
def top_selling_products(user=Depends(auth_required)):
    try:
        store_id = user["store_id"]

        result = (
            supabase.table("top_sellers_report")
            .select("*")
            .eq("store_id", store_id)
            .execute()
        )
        return result.data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
