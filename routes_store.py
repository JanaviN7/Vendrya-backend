from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from supabase_client import supabase
from typing import Optional
import os
from pydantic import BaseModel
from auth.dependencies import auth_required

router = APIRouter(prefix="/store", tags=["Store"])


# =======================
# SCHEMAS
# =======================

class UPIRequest(BaseModel):
    upi_id: str


class StoreSettingsUpdate(BaseModel):
    upi_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    gstin: Optional[str] = None
    logo_url: Optional[str] = None
    language: Optional[str] = None     # ✅ NEW — en, hi, te, gu


BUCKET_NAME = "store-logos"


# =======================
# GET STORE CONTEXT
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


# =======================
# GET STORE SETTINGS
# =======================

@router.get("/settings")
def get_store_settings(user=Depends(auth_required)):
    store_id = user["store_id"]

    res = (
        supabase.table("store_settings")
        .select("upi_id,address,phone,gstin,logo_url,language,updated_at")
        .eq("store_id", store_id)
        .limit(1)
        .execute()
    )

    data = res.data or []
    if not data:
        return {"success": True, "settings": {}}

    return {"success": True, "settings": data[0]}


# =======================
# ✅ SAVE STORE SETTINGS
# This was missing — frontend calls POST /store/settings
# =======================

@router.post("/settings")
def save_store_settings(payload: StoreSettingsUpdate, user=Depends(auth_required)):
    store_id = user["store_id"]

    # ✅ Only admin can save settings
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin can update store settings"
        )

    # Build update data — only include fields that were provided
    update_data = {"store_id": store_id}

    if payload.upi_id is not None:
        update_data["upi_id"] = payload.upi_id.strip()
    if payload.address is not None:
        update_data["address"] = payload.address.strip()
    if payload.phone is not None:
        update_data["phone"] = payload.phone.strip()
    if payload.gstin is not None:
        update_data["gstin"] = payload.gstin.strip().upper()
    if payload.logo_url is not None:
        update_data["logo_url"] = payload.logo_url
    if payload.language is not None:
        update_data["language"] = payload.language  # "en", "hi", "te", "gu"

    # ✅ Add updated timestamp
    from datetime import datetime, timezone
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # ✅ Upsert — creates if not exists, updates if exists
    result = supabase.table("store_settings").upsert(update_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save settings")

    return {
        "success": True,
        "message": "Settings saved successfully",
        "settings": result.data[0]
    }


# =======================
# ✅ SAVE LANGUAGE PREFERENCE ONLY
# Quick endpoint for language switcher
# =======================

@router.post("/language")
def save_language(
    payload: dict,
    user=Depends(auth_required)
):
    store_id = user["store_id"]
    language = payload.get("language", "en")

    if language not in ("en", "hi", "te", "gu"):
        raise HTTPException(status_code=400, detail="Invalid language code")

    from datetime import datetime, timezone
    supabase.table("store_settings").upsert({
        "store_id": store_id,
        "language": language,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    return {
        "success": True,
        "message": "Language preference saved",
        "language": language
    }


# =======================
# UPLOAD STORE LOGO
# =======================

@router.post("/upload-logo/{store_id}")
async def upload_store_logo(
    store_id: str,
    file: UploadFile = File(...),
    user=Depends(auth_required)
):
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

        from datetime import datetime, timezone
        supabase.table("store_settings").upsert({
            "store_id": store_id,
            "logo_url": public_url,
            "updated_at": datetime.now(timezone.utc).isoformat()
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
# SAVE UPI ID
# =======================

@router.post("/upi")
def save_upi(payload: UPIRequest, user=Depends(auth_required)):
    upi = payload.upi_id.strip()

    if not upi:
        raise HTTPException(status_code=400, detail="UPI ID is required")

    from datetime import datetime, timezone
    supabase.table("store_settings").upsert({
        "store_id": user["store_id"],
        "upi_id": upi,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    return {"success": True, "message": "UPI saved"}


# =======================
# ✅ ADD LANGUAGE COLUMN TO SUPABASE
# Run this in Supabase SQL Editor if not already done:
# ALTER TABLE store_settings ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en';
# =======================