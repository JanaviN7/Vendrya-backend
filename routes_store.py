# routes_store.py
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from supabase_client import supabase
#import uuid
from typing import Optional
import os
from pydantic import BaseModel
from auth.dependencies import auth_required   # or wherever auth_required is

router = APIRouter(prefix="/store", tags=["Store"])
class UPIRequest(BaseModel):
    upi_id: str

class StoreSettingsUpdate(BaseModel):
    upi_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    gstin: Optional[str] = None
    logo_url: Optional[str] = None

BUCKET_NAME = "store-logos"
# =======================
# GET STORE CONTEXT (ADMIN)
# =======================
@router.get("/me")
def get_my_store(user=Depends(auth_required)):
    store = (
        supabase.table("stores")
        .select("store_id,store_name,categories,created_at")
        .eq("store_id", user["store_id"])
        .single()
        .execute()
    )

    if not store.data:
        raise HTTPException(status_code=404, detail="Store not found")

    return {"success": True, "store": store.data}

@router.get("/settings")
def get_store_settings(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("store_settings")
        .select("upi_id,address,phone,gstin,logo_url,updated_at")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )

    data = (res.data or [])
    if not data:
        return {"success": True, "settings": {}}

    return {"success": True, "settings": data[0]}


# =======================
# UPLOAD STORE LOGO
# =======================
@router.post("/upload-logo/{store_id}")
async def upload_store_logo(store_id: str, file: UploadFile = File(...), user=Depends(auth_required)):

    if user["store_id"] != store_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only .png/.jpg files allowed")

    ext = os.path.splitext(file.filename)[1]
    file_path = f"{store_id}{ext}"

    try:
        file_bytes = await file.read()
        supabase.storage.from_(BUCKET_NAME).upload(file_path, file_bytes)

        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

        # ✅ auto save logo url into store_settings
        supabase.table("store_settings").upsert({
            "store_id": store_id,
            "logo_url": public_url
        }).execute()

        return {
            "success": True,
            "message": "Logo uploaded successfully",
            "store_id": store_id,
            "logo_url": public_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =======================
# SAVE STORE UPI ID
# =======================
@router.post("/upi")
def save_upi(payload: UPIRequest, user=Depends(auth_required)):
    upi = payload.upi_id.strip()

    if not upi:
        raise HTTPException(status_code=400, detail="UPI ID is required")

    supabase.table("store_settings").upsert({
        "store_id": user["store_id"],
        "upi_id": upi
    }).execute()

    return {"success": True, "message": "UPI saved"}
