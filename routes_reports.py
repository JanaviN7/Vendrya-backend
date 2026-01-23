from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date
from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/reports", tags=["Reports"])


# =====================================================
# 🔒 ADMIN CHECK
# =====================================================
def admin_only(user):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _display_name(user_row: dict) -> str:
    """Show admin clearly as Owner (Admin)."""
    role = user_row.get("role")
    name = user_row.get("name") or "Unknown"
    if role == "admin":
        return "Owner (Admin)"
    return name


# ==========================
# TODAY SALES REPORT
# ==========================
@router.get("/today")
def today_report(user=Depends(auth_required)):
    store_id = user["store_id"]
    today = date.today().isoformat()

    sales = (
        supabase.table("sales")
        .select("sale_id,total_amount")
        .eq("store_id", store_id)
        .gte("sale_timestamp", f"{today}T00:00:00")
        .lte("sale_timestamp", f"{today}T23:59:59")
        .execute()
    ).data or []

    total_orders = len(sales)
    total_sales_amount = sum(float(s["total_amount"]) for s in sales)

    sale_ids = [s["sale_id"] for s in sales]

    total_items_sold = 0
    if sale_ids:
        items = (
            supabase.table("sale_items")
            .select("quantity")
            .in_("sale_id", sale_ids)
            .execute()
        ).data or []
        total_items_sold = sum(int(i["quantity"]) for i in items)

    return {
        "success": True,
        "date": today,
        "total_orders": total_orders,
        "total_items_sold": total_items_sold,
        "total_sales_amount": total_sales_amount
    }


# ==========================
# DAILY SALES (ALL DAYS)
# ==========================
@router.get("/daily")
def daily_report(user=Depends(auth_required)):
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("total_amount,sale_timestamp")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    daily = {}
    for s in sales:
        day = s["sale_timestamp"][:10]
        daily.setdefault(day, 0.0)
        daily[day] += float(s["total_amount"])

    return [
        {"date": d, "total_sales_amount": daily[d]}
        for d in sorted(daily.keys())
    ]


# ==========================
# MONTHLY SALES
# ==========================
@router.get("/monthly")
def monthly_report(user=Depends(auth_required)):
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("total_amount,sale_timestamp")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    monthly = {}
    for s in sales:
        month = s["sale_timestamp"][:7]  # YYYY-MM
        monthly.setdefault(month, 0.0)
        monthly[month] += float(s["total_amount"])

    return [
        {"month": m, "total_sales_amount": monthly[m]}
        for m in sorted(monthly.keys())
    ]


# ==========================
# LOW STOCK REPORT
# ==========================
@router.get("/low-stock")
def low_stock_report(
    threshold: int = Query(10, description="Stock alert threshold"),
    user=Depends(auth_required)
):
    store_id = user["store_id"]

    products = (
        supabase.table("products")
        .select("product_id,name,barcode,quantity")
        .eq("store_id", store_id)
        .lte("quantity", threshold)
        .order("quantity")
        .execute()
    ).data or []

    return {
        "success": True,
        "threshold": threshold,
        "total_low_stock_items": len(products),
        "products": products
    }


# ==========================
# TOP PRODUCTS
# ==========================
@router.get("/top-products")
def top_selling_products(user=Depends(auth_required)):
    store_id = user["store_id"]

    data = (
        supabase.table("sale_items")
        .select("product_id, quantity, price, products(name, barcode), sales(store_id)")
        .eq("sales.store_id", store_id)
        .execute()
    ).data or []

    summary = {}
    for row in data:
        pid = row["product_id"]
        qty = int(row["quantity"])
        revenue = qty * float(row["price"])

        if pid not in summary:
            summary[pid] = {
                "product_id": pid,
                "name": row["products"]["name"] if row.get("products") else None,
                "barcode": row["products"]["barcode"] if row.get("products") else None,
                "total_quantity_sold": 0,
                "total_revenue": 0.0
            }

        summary[pid]["total_quantity_sold"] += qty
        summary[pid]["total_revenue"] += revenue

    result = sorted(summary.values(), key=lambda x: x["total_quantity_sold"], reverse=True)

    return {
        "success": True,
        "total_products": len(result),
        "top_products": result
    }


# =====================================================
# 1️⃣ DATE-RANGE STAFF SALES REPORT
# ✅ Includes OWNER too (Admin sales)
# =====================================================
@router.get("/staff-sales/range")
def staff_sales_date_range(
    start_date: date = Query(...),
    end_date: date = Query(...),
    user=Depends(auth_required)
):
    admin_only(user)
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("staff_id, total_amount")
        .eq("store_id", store_id)
        .gte("sale_timestamp", f"{start_date}T00:00:00")
        .lte("sale_timestamp", f"{end_date}T23:59:59")
        .execute()
    ).data or []

    # ✅ include admin + staff
    staff = (
        supabase.table("store_users")
        .select("user_id, name, email, role")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    staff_map = {
        s["user_id"]: {
            "staff_id": s["user_id"],
            "name": _display_name(s),
            "email": s.get("email"),
            "role": s.get("role"),
            "total_sales": 0.0,
            "orders": 0
        }
        for s in staff
    }

    for sale in sales:
        sid = sale.get("staff_id")
        if sid in staff_map:
            staff_map[sid]["total_sales"] += float(sale["total_amount"])
            staff_map[sid]["orders"] += 1

    return {
        "success": True,
        "range": {"from": str(start_date), "to": str(end_date)},
        "data": list(staff_map.values())
    }


# =====================================================
# 2️⃣ STAFF LEADERBOARD
# ✅ Includes OWNER too (Admin sales)
# =====================================================
@router.get("/staff-sales/leaderboard")
def staff_leaderboard(user=Depends(auth_required)):
    admin_only(user)
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("staff_id, total_amount")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    staff = (
        supabase.table("store_users")
        .select("user_id, name, role")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    summary = {
        s["user_id"]: {
            "staff_id": s["user_id"],
            "name": _display_name(s),
            "role": s.get("role"),
            "total_sales": 0.0
        }
        for s in staff
    }

    for sale in sales:
        sid = sale.get("staff_id")
        if sid in summary:
            summary[sid]["total_sales"] += float(sale["total_amount"])

    leaderboard = sorted(summary.values(), key=lambda x: x["total_sales"], reverse=True)

    return {"success": True, "leaderboard": leaderboard}


# =====================================================
# 3️⃣ PER-STAFF DAILY SALES GRAPH
# =====================================================
@router.get("/staff-sales/daily")
def staff_daily_graph(
    staff_id: str = Query(...),
    user=Depends(auth_required)
):
    admin_only(user)
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("sale_timestamp, total_amount")
        .eq("store_id", store_id)
        .eq("staff_id", staff_id)
        .execute()
    ).data or []

    daily = {}
    for s in sales:
        day = s["sale_timestamp"][:10]
        daily.setdefault(day, 0.0)
        daily[day] += float(s["total_amount"])

    graph = [{"date": d, "sales": daily[d]} for d in sorted(daily)]

    return {"success": True, "staff_id": staff_id, "graph": graph}


# =====================================================
# 4️⃣ STAFF DASHBOARD SUMMARY
# ✅ Includes OWNER too (Admin sales)
# =====================================================
@router.get("/staff-sales/dashboard")
def staff_dashboard(user=Depends(auth_required)):
    admin_only(user)
    store_id = user["store_id"]

    sales = (
        supabase.table("sales")
        .select("staff_id, total_amount")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    staff = (
        supabase.table("store_users")
        .select("user_id, name, role")
        .eq("store_id", store_id)
        .execute()
    ).data or []

    staff_map = {
        s["user_id"]: {
            "staff_id": s["user_id"],
            "name": _display_name(s),
            "role": s.get("role"),
            "orders": 0,
            "revenue": 0.0
        }
        for s in staff
    }

    total_revenue = 0.0
    total_orders = 0

    for sale in sales:
        sid = sale.get("staff_id")
        amt = float(sale["total_amount"])

        total_revenue += amt
        total_orders += 1

        if sid in staff_map:
            staff_map[sid]["orders"] += 1
            staff_map[sid]["revenue"] += amt

    return {
        "success": True,
        "metrics": {
            "total_revenue": total_revenue,
            "total_orders": total_orders
        },
        "staff": list(staff_map.values())
    }
