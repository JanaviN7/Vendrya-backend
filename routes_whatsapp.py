from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from supabase_client import supabase
import config
from auth.dependencies import auth_required
from whatsapp_service import send_whatsapp_message

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


class SaveVendorWhatsApp(BaseModel):
    phone_number_id: str
    access_token: str


@router.post("/config/{store_id}")
def save_whatsapp_config(
    store_id: str,
    payload: SaveVendorWhatsApp,
    user=Depends(auth_required)
):
    if user["store_id"] != store_id or user["role"] not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Not allowed")

    res = supabase.table("vendor_whatsapp").upsert(
        {
            "store_id": store_id,
            "phone_number_id": payload.phone_number_id,
            "access_token": payload.access_token,
        },
        on_conflict="store_id"
    ).execute()

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed saving config")

    return {"message": "WhatsApp config saved"}


@router.post("/send")
def send_bill(
    phone: str = Query(...),
    amount: float = Query(...),
    customer: str | None = Query(None),
    store_id: str | None = Query(None),
):
    to = phone.strip().replace(" ", "").lstrip("+")

    if store_id:
        cfg = (
            supabase.table("vendor_whatsapp")
            .select("*")
            .eq("store_id", store_id)
            .single()
            .execute()
        )
        if not cfg.data:
            raise HTTPException(status_code=400, detail="No WhatsApp config for store")

        phone_number_id = cfg.data["phone_number_id"]
        access_token = cfg.data["access_token"]
    else:
        phone_number_id = config.WHATSAPP_PHONE_NUMBER_ID
        access_token = config.WHATSAPP_ACCESS_TOKEN

        if not phone_number_id or not access_token:
            raise HTTPException(status_code=500, detail="WhatsApp credentials missing")

    body = f"Hello {customer + ', ' if customer else ''}your bill is ₹{amount:.2f}. Thank you!"

    return send_whatsapp_message(to, body)
