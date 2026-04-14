from dotenv import load_dotenv
load_dotenv()

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
#from routes_dues import router as dues_router
from routes_ledger import router as ledger_router
from routes_reminders import router as reminders_router
from routes_invoice import router as invoice_router
from routes_subscription import router as subscription_router
from routes_export import router as export_router
from routes_favourites import router as favourites_router
from routes_cash import router as cash_router
from routes_customers import router as customers_router
from routes_reorder import router as reorder_router
from routes_voice import router as voice_router
app = FastAPI(title="Ventsa API")

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
            "service": "Ventsa API"}

# ✅ ROOT
@app.get("/")
def root():
    return {"message": "Ventsa API running"}

# ✅ ROUTES
app.include_router(auth_router)
app.include_router(store_router)
app.include_router(staff_router)

app.include_router(product_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(reports_router)

app.include_router(whatsapp_router)
#app.include_router(dues_router)
app.include_router(ledger_router)
app.include_router(reminders_router)
app.include_router(invoice_router)
app.include_router(subscription_router)
app.include_router(export_router)
app.include_router(favourites_router)
app.include_router(cash_router)
app.include_router(customers_router)
app.include_router(voice_router)
app.include_router(reorder_router)