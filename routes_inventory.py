from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from supabase_client import supabase
from auth.dependencies import auth_required
from datetime import date, datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional
import httpx
import config

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# ==========================
# SCHEMAS
# ==========================

class LowStockAlertSettings(BaseModel):
    enabled: bool = True
    threshold: int = 5          # alert when qty falls below this
    email: Optional[str] = None # override email, else uses store owner email


# ==========================
# HELPERS
# ==========================

def send_low_stock_email(to_email: str, store_name: str, low_stock_items: list):
    """Send low stock alert email via Brevo."""
    if not config.BREVO_API_KEY:
        print(f"[DEV] Low stock alert for {store_name}: {len(low_stock_items)} items")
        return

    # Build items table HTML
    items_html = ""
    for item in low_stock_items:
        qty = item.get("quantity", 0)
        name = item.get("name", "Unknown")
        threshold = item.get("threshold_qty", 5)
        color = "#ef4444" if qty == 0 else "#f97316"
        items_html += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:14px;">{name}</td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;text-align:center;">
                <span style="background:{color};color:white;padding:2px 10px;
                border-radius:12px;font-size:13px;font-weight:600;">
                    {qty} left
                </span>
            </td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;text-align:center;
                color:#6b7280;font-size:13px;">
                Min: {threshold}
            </td>
        </tr>
        """

    out_of_stock = [i for i in low_stock_items if i.get("quantity", 0) == 0]
    low_stock = [i for i in low_stock_items if i.get("quantity", 0) > 0]

    summary = ""
    if out_of_stock:
        summary += f'<p style="color:#ef4444;font-weight:600;">⚠️ {len(out_of_stock)} item(s) are OUT OF STOCK!</p>'
    if low_stock:
        summary += f'<p style="color:#f97316;font-weight:600;">📦 {len(low_stock)} item(s) running low</p>'

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;
  font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
    style="background:#f4f4f7;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
        style="background:#ffffff;border-radius:12px;overflow:hidden;
        box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1,#14b8a6);
            padding:28px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">
              📦 Low Stock Alert
            </h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
              {store_name} · Ventsa
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 40px 24px;">
            <p style="color:#374151;font-size:15px;margin:0 0 8px;">
              Hi! Your store needs restocking.
            </p>
            {summary}
            <table width="100%" style="border-collapse:collapse;margin-top:16px;">
              <thead>
                <tr style="background:#f3f4f6;">
                  <th style="padding:10px;text-align:left;font-size:13px;
                    color:#6b7280;font-weight:600;">Product</th>
                  <th style="padding:10px;text-align:center;font-size:13px;
                    color:#6b7280;font-weight:600;">Stock</th>
                  <th style="padding:10px;text-align:center;font-size:13px;
                    color:#6b7280;font-weight:600;">Threshold</th>
                </tr>
              </thead>
              <tbody>{items_html}</tbody>
            </table>
            <p style="margin:20px 0 0;color:#6b7280;font-size:13px;">
              Login to Ventsa to update your stock levels.
            </p>
            <a href="https://ventsa.lovable.app/inventory"
              style="display:inline-block;margin-top:16px;
              background:linear-gradient(135deg,#6366f1,#14b8a6);
              color:white;padding:12px 28px;border-radius:8px;
              text-decoration:none;font-size:14px;font-weight:600;">
              Update Stock Now →
            </a>
          </td>
        </tr>
        <tr>
          <td style="background:#f9fafb;padding:16px 40px;
            border-top:1px solid #e5e7eb;">
            <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
              © 2026 Ventsa · Simple Billing. Smart Business.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    try:
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": config.BREVO_API_KEY,
                "content-type": "application/json"
            },
            json={
                "sender": {
                    "name": "Ventsa Alerts",
                    "email": config.BREVO_SENDER_EMAIL
                },
                "to": [{"email": to_email}],
                "subject": f"⚠️ Low Stock Alert — {len(low_stock_items)} items need restocking",
                "htmlContent": html_body
            },
            timeout=10.0
        )
        response.raise_for_status()
        print(f"✅ Low stock alert sent to {to_email}")
    except Exception as e:
        print(f"⚠️ Low stock alert email failed: {str(e)}")


# ==========================
# INVENTORY LOGS (ALL)
# ==========================

@router.get("/logs")
def get_inventory_logs(user=Depends(auth_required)):
    res = (
        supabase.table("inventory_logs")
        .select("""
            log_id,
            product_id,
            qty_changed,
            action_type,
            timestamp,
            products(name, barcode)
        """)
        .eq("store_id", user["store_id"])
        .order("timestamp", desc=True)
        .execute()
    )
    return {"success": True, "data": res.data or []}


# ==========================
# INVENTORY LOGS BY PRODUCT
# ==========================

@router.get("/logs/product/{product_id}")
def get_product_inventory_logs(product_id: str, user=Depends(auth_required)):
    res = (
        supabase.table("inventory_logs")
        .select("log_id, qty_changed, action_type, timestamp")
        .eq("store_id", user["store_id"])
        .eq("product_id", product_id)
        .order("timestamp", desc=True)
        .execute()
    )
    return {"success": True, "product_id": product_id, "logs": res.data or []}


# ==========================
# INVENTORY LOGS BY DATE
# ==========================

@router.get("/logs/date/{log_date}")
def get_inventory_logs_by_date(log_date: date, user=Depends(auth_required)):
    start = f"{log_date}T00:00:00"
    end = f"{log_date}T23:59:59"

    res = (
        supabase.table("inventory_logs")
        .select("log_id, product_id, qty_changed, action_type, timestamp, products(name)")
        .eq("store_id", user["store_id"])
        .gte("timestamp", start)
        .lte("timestamp", end)
        .order("timestamp", desc=True)
        .execute()
    )
    return {"success": True, "date": str(log_date), "logs": res.data or []}


# ==========================
# LOW STOCK PRODUCTS
# ==========================

@router.get("/low-stock")
def low_stock_products(user=Depends(auth_required)):
    res = (
        supabase.table("products")
        .select("product_id, name, quantity, threshold_qty, category")
        .eq("store_id", user["store_id"])
        .execute()
    )
    products = res.data or []

    # Filter where quantity < threshold_qty
    low = [
        p for p in products
        if int(p.get("quantity", 0)) < int(p.get("threshold_qty", 5))
    ]
    low_sorted = sorted(low, key=lambda x: x.get("quantity", 0))

    return {"success": True, "data": low_sorted}


# ==========================
# ✅ SEND LOW STOCK ALERT EMAIL
# Admin triggers this manually OR auto-triggered
# ==========================

@router.post("/low-stock/alert")
def send_low_stock_alert(
    background_tasks: BackgroundTasks,
    user=Depends(auth_required)
):
    """
    Manually trigger a low stock alert email.
    Sends to the store owner's email.
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can send stock alerts"
        )

    store_id = user["store_id"]

    # Get store name
    store_res = supabase.table("stores") \
        .select("store_name") \
        .eq("store_id", store_id) \
        .single() \
        .execute()
    store_name = store_res.data.get("store_name", "Your Store") if store_res.data else "Your Store"

    # Get owner email
    owner_res = supabase.table("store_users") \
        .select("email") \
        .eq("store_id", store_id) \
        .eq("role", "admin") \
        .limit(1) \
        .execute()

    if not owner_res.data:
        raise HTTPException(status_code=404, detail="Store owner email not found")

    owner_email = owner_res.data[0]["email"]

    # Get low stock products
    products_res = supabase.table("products") \
        .select("product_id, name, quantity, threshold_qty, category") \
        .eq("store_id", store_id) \
        .execute()

    products = products_res.data or []
    low_stock_items = [
        p for p in products
        if int(p.get("quantity", 0)) < int(p.get("threshold_qty", 5))
    ]

    if not low_stock_items:
        return {
            "success": True,
            "message": "No low stock items found. All products are well stocked! ✅",
            "items_count": 0
        }

    # ✅ Send email in background so API responds fast
    background_tasks.add_task(
        send_low_stock_email,
        owner_email,
        store_name,
        low_stock_items
    )

    return {
        "success": True,
        "message": f"Low stock alert sent to {owner_email}",
        "items_count": len(low_stock_items),
        "items": [
            {
                "name": i["name"],
                "quantity": i["quantity"],
                "threshold": i.get("threshold_qty", 5)
            }
            for i in low_stock_items
        ]
    }


# ==========================
# ✅ AUTO LOW STOCK CHECK
# Called after every sale to auto-send alert
# if any product hits threshold
# Import and call this from routes_sales.py
# ==========================

def auto_check_low_stock(store_id: str, product_ids: list):
    """
    Auto-check stock levels after a sale.
    Sends email if any product crosses below threshold.
    Called in background from create_sale.
    """
    try:
        products_res = supabase.table("products") \
            .select("product_id, name, quantity, threshold_qty") \
            .eq("store_id", store_id) \
            .in_("product_id", product_ids) \
            .execute()

        products = products_res.data or []
        newly_low = [
            p for p in products
            if int(p.get("quantity", 0)) < int(p.get("threshold_qty", 5))
        ]

        if not newly_low:
            return

        # Get store info
        store_res = supabase.table("stores") \
            .select("store_name") \
            .eq("store_id", store_id) \
            .single() \
            .execute()
        store_name = store_res.data.get("store_name", "Your Store") if store_res.data else "Your Store"

        owner_res = supabase.table("store_users") \
            .select("email") \
            .eq("store_id", store_id) \
            .eq("role", "admin") \
            .limit(1) \
            .execute()

        if owner_res.data:
            owner_email = owner_res.data[0]["email"]
            send_low_stock_email(owner_email, store_name, newly_low)

    except Exception as e:
        print(f"⚠️ Auto low stock check failed: {str(e)}")


# ==========================
# INVENTORY ANALYTICS
# ==========================

@router.get("/analytics")
def inventory_analytics(user=Depends(auth_required)):
    store_id = user["store_id"]

    products_res = supabase.table("products") \
        .select("product_id, name, category, quantity, price, cost_price") \
        .eq("store_id", store_id) \
        .execute()
    products = products_res.data or []
    product_map = {p["product_id"]: p for p in products}

    sale_items_res = supabase.table("sale_items") \
        .select("product_id, quantity, price, total") \
        .eq("store_id", store_id) \
        .execute()
    sale_items = sale_items_res.data or []

    logs_res = supabase.table("inventory_logs") \
        .select("product_id, qty_changed, action_type, timestamp") \
        .eq("store_id", store_id) \
        .execute()
    logs = logs_res.data or []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_sales_res = supabase.table("sale_items") \
        .select("product_id") \
        .eq("store_id", store_id) \
        .gte("created_at", cutoff) \
        .execute()
    recently_sold_ids = {s["product_id"] for s in (recent_sales_res.data or [])}

    sales_map = {}
    for item in sale_items:
        pid = item["product_id"]
        if pid not in sales_map:
            sales_map[pid] = {"units_sold": 0, "revenue": 0.0}
        sales_map[pid]["units_sold"] += int(item.get("quantity", 0))
        sales_map[pid]["revenue"] += float(item.get("total", 0))

    imported_map = {}
    for log in logs:
        if log["action_type"] == "add":
            pid = log["product_id"]
            imported_map[pid] = imported_map.get(pid, 0) + int(log.get("qty_changed", 0))

    product_analytics = []
    category_map = {}

    for p in products:
        pid = p["product_id"]
        sold = sales_map.get(pid, {})
        units_sold = sold.get("units_sold", 0)
        revenue = sold.get("revenue", 0.0)
        imported = imported_map.get(pid, 0)

        selling_price = float(p.get("price", 0))
        cost_price = float(p.get("cost_price", 0))
        current_qty = int(p.get("quantity", 0))

        profit = (selling_price - cost_price) * units_sold if cost_price > 0 else None
        profit_margin = ((selling_price - cost_price) / selling_price * 100) \
            if cost_price > 0 and selling_price > 0 else None
        stock_value = cost_price * current_qty if cost_price > 0 else selling_price * current_qty
        is_dead_stock = pid not in recently_sold_ids and units_sold == 0

        pa = {
            "product_id": pid,
            "name": p["name"],
            "category": p.get("category", "Uncategorized"),
            "current_qty": current_qty,
            "units_sold": units_sold,
            "total_imported": imported,
            "revenue": revenue,
            "profit": profit,
            "profit_margin": round(profit_margin, 1) if profit_margin is not None else None,
            "selling_price": selling_price,
            "cost_price": cost_price,
            "stock_value": round(stock_value, 2),
            "is_dead_stock": is_dead_stock,
        }
        product_analytics.append(pa)

        cat = p.get("category") or "Uncategorized"
        if cat not in category_map:
            category_map[cat] = {
                "category": cat, "stock_value": 0.0,
                "revenue": 0.0, "profit": 0.0, "product_count": 0
            }
        category_map[cat]["stock_value"] += stock_value
        category_map[cat]["revenue"] += revenue
        if profit is not None:
            category_map[cat]["profit"] += profit
        category_map[cat]["product_count"] += 1

    top_sellers = sorted(
        [p for p in product_analytics if p["units_sold"] > 0],
        key=lambda x: x["units_sold"], reverse=True
    )[:5]

    dead_stock = [p for p in product_analytics if p["is_dead_stock"]]
    total_stock_value = sum(p["stock_value"] for p in product_analytics)
    total_revenue = sum(p["revenue"] for p in product_analytics)
    total_profit = sum(p["profit"] for p in product_analytics if p["profit"] is not None)
    total_units_sold = sum(p["units_sold"] for p in product_analytics)
    total_imported = sum(p["total_imported"] for p in product_analytics)

    return {
        "success": True,
        "summary": {
            "total_products": len(products),
            "total_stock_value": round(total_stock_value, 2),
            "total_revenue": round(total_revenue, 2),
            "total_profit": round(total_profit, 2),
            "total_units_sold": total_units_sold,
            "total_imported": total_imported,
            "dead_stock_count": len(dead_stock),
        },
        "top_sellers": top_sellers,
        "dead_stock": dead_stock,
        "by_category": sorted(
            category_map.values(),
            key=lambda x: x["revenue"], reverse=True
        ),
        "products": product_analytics,
    }