from fastapi import APIRouter, Depends, HTTPException
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/reorder", tags=["Reorder"])

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


# ==========================
# ✅ GET REORDER SUGGESTIONS
# Analyzes sales velocity to predict when stock will run out
# "You usually sell 2kg rice/day. Only 3kg left. Order soon!"
# ==========================

@router.get("/suggestions")
def get_reorder_suggestions(user=Depends(auth_required)):
    """
    Smart reorder suggestions based on:
    1. Current stock level
    2. Average daily sales velocity (last 30 days)
    3. Days until stockout
    4. Threshold qty set by admin

    Returns products that need ordering soon.
    """
    store_id = user["store_id"]

    # Get all products
    products_res = supabase.table("products") \
        .select("product_id, name, category, quantity, threshold_qty, price, unit") \
        .eq("store_id", store_id) \
        .execute()

    products = products_res.data or []
    if not products:
        return {"success": True, "suggestions": [], "message": "No products found"}

    product_ids = [p["product_id"] for p in products]
    product_map = {p["product_id"]: p for p in products}

    # Get last 30 days sales for all products
    cutoff_30 = (now_ist() - timedelta(days=30)).isoformat()
    cutoff_7 = (now_ist() - timedelta(days=7)).isoformat()

    sales_30_res = supabase.table("sale_items") \
        .select("product_id, quantity") \
        .eq("store_id", store_id) \
        .gte("created_at", cutoff_30) \
        .execute()

    sales_7_res = supabase.table("sale_items") \
        .select("product_id, quantity") \
        .eq("store_id", store_id) \
        .gte("created_at", cutoff_7) \
        .execute()

    # Aggregate sales by product
    sales_30 = {}
    for item in (sales_30_res.data or []):
        pid = item["product_id"]
        sales_30[pid] = sales_30.get(pid, 0) + int(item.get("quantity", 0))

    sales_7 = {}
    for item in (sales_7_res.data or []):
        pid = item["product_id"]
        sales_7[pid] = sales_7.get(pid, 0) + int(item.get("quantity", 0))

    suggestions = []

    for product in products:
        pid = product["product_id"]
        current_qty = float(product.get("quantity", 0))
        threshold = float(product.get("threshold_qty", 5))

        # Calculate daily velocity
        sold_30 = sales_30.get(pid, 0)
        sold_7 = sales_7.get(pid, 0)

        # Use 7-day velocity if available (more recent), else 30-day
        if sold_7 > 0:
            daily_velocity = sold_7 / 7
        elif sold_30 > 0:
            daily_velocity = sold_30 / 30
        else:
            daily_velocity = 0  # no sales data

        # Calculate days until stockout
        if daily_velocity > 0:
            days_until_stockout = current_qty / daily_velocity
        else:
            days_until_stockout = 999  # effectively infinite

        # Determine urgency
        urgency = None
        urgency_color = None
        message = None

        if current_qty == 0:
            urgency = "out_of_stock"
            urgency_color = "#ef4444"
            message = "Out of stock! Order immediately."

        elif current_qty <= threshold:
            urgency = "critical"
            urgency_color = "#ef4444"
            if daily_velocity > 0:
                message = f"Only {current_qty:.0f} left. Will run out in ~{days_until_stockout:.0f} days."
            else:
                message = f"Only {current_qty:.0f} left (below threshold of {threshold:.0f})."

        elif days_until_stockout <= 7 and daily_velocity > 0:
            urgency = "urgent"
            urgency_color = "#f97316"
            message = f"Selling {daily_velocity:.1f}/day. Will run out in ~{days_until_stockout:.0f} days!"

        elif days_until_stockout <= 14 and daily_velocity > 0:
            urgency = "soon"
            urgency_color = "#eab308"
            message = f"Selling {daily_velocity:.1f}/day. Consider restocking in a few days."

        # Only include if needs attention
        if urgency:
            # Suggest order quantity (enough for 30 days)
            suggested_order_qty = max(
                threshold * 2,
                daily_velocity * 30 if daily_velocity > 0 else threshold * 2
            )

            suggestions.append({
                "product_id": pid,
                "name": product["name"],
                "category": product.get("category", "Uncategorized"),
                "current_qty": current_qty,
                "threshold_qty": threshold,
                "daily_velocity": round(daily_velocity, 2),
                "days_until_stockout": round(days_until_stockout, 1) if days_until_stockout < 999 else None,
                "sold_last_7_days": sold_7,
                "sold_last_30_days": sold_30,
                "urgency": urgency,
                "urgency_color": urgency_color,
                "message": message,
                "suggested_order_qty": round(suggested_order_qty, 0),
                "unit": product.get("unit", "units"),
                "price": product.get("price", 0)
            })

    # Sort by urgency: out_of_stock first, then critical, urgent, soon
    urgency_order = {"out_of_stock": 0, "critical": 1, "urgent": 2, "soon": 3}
    suggestions.sort(key=lambda x: urgency_order.get(x["urgency"], 99))

    return {
        "success": True,
        "suggestions": suggestions,
        "total": len(suggestions),
        "out_of_stock": len([s for s in suggestions if s["urgency"] == "out_of_stock"]),
        "critical": len([s for s in suggestions if s["urgency"] == "critical"]),
        "urgent": len([s for s in suggestions if s["urgency"] == "urgent"]),
        "message": f"{len(suggestions)} products need attention" if suggestions
                   else "All products are well stocked! ✅"
    }


# ==========================
# ✅ GET REORDER SUMMARY
# Quick count for dashboard badge
# ==========================

@router.get("/summary")
def get_reorder_summary(user=Depends(auth_required)):
    """Quick summary for dashboard notification badge."""
    store_id = user["store_id"]

    # Out of stock
    out_res = supabase.table("products") \
        .select("product_id", count="exact") \
        .eq("store_id", store_id) \
        .eq("quantity", 0) \
        .execute()

    # Below threshold
    products_res = supabase.table("products") \
        .select("quantity, threshold_qty") \
        .eq("store_id", store_id) \
        .execute()

    low_stock_count = 0
    for p in (products_res.data or []):
        qty = float(p.get("quantity", 0))
        threshold = float(p.get("threshold_qty", 5))
        if 0 < qty <= threshold:
            low_stock_count += 1

    out_of_stock = out_res.count or 0
    total_attention = out_of_stock + low_stock_count

    return {
        "success": True,
        "out_of_stock": out_of_stock,
        "low_stock": low_stock_count,
        "total_needs_attention": total_attention,
        "badge_count": total_attention
    }