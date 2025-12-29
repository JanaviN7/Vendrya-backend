from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes_products import router as product_router
from routes_sales import router as sales_router
from routes_reports import router as reports_router
from routes_inventory import router as inventory_router
from routes_store import router as store_router
from routes_auth import router as auth_router
from routes_staff import router as staff_router
from routes_whatsapp import router as whatsapp_router
from routes_dues import router as dues_router
from routes_ledger import router as ledger_router
from routes_reminders import router as reminders_router

app = FastAPI(title="Smart POS API")

# 🔥 CORS — MUST be BEFORE routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # OK for dev (ngrok + lovable)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],         # IMPORTANT for auth headers
)

# ✅ HEALTH CHECK (Lovable REQUIRES THIS)
@app.get("/health")
def health():
    return {"status": "ok",
            "service": "Smart POS API"}

# ✅ ROOT
@app.get("/")
def root():
    return {"message": "Smart POS API running"}

# ✅ ROUTES
app.include_router(auth_router)
app.include_router(store_router)
app.include_router(staff_router)

app.include_router(product_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(reports_router)

app.include_router(whatsapp_router)
app.include_router(dues_router)
app.include_router(ledger_router)
app.include_router(reminders_router)
