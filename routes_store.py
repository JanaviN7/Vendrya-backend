# routes_store.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from supabase_client import supabase
import uuid
import os
from fastapi import APIRouter, Depends
from auth.dependencies import auth_required   # or wherever auth_required is

router = APIRouter(prefix="/store", tags=["Store"])

BUCKET_NAME = "store-logos"

@router.post("/upload-logo/{store_id}")
async def upload_store_logo(store_id: str, file: UploadFile = File(...)):

    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only .png/.jpg files allowed")

    ext = os.path.splitext(file.filename)[1]
    file_path = f"{store_id}{ext}"

    try:
        file_bytes = await file.read()
        supabase.storage.from_(BUCKET_NAME).upload(file_path, file_bytes)

        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

        return {
            "message": "Logo uploaded successfully",
            "store_id": store_id,
            "logo_url": public_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/store/upi")
def save_upi(upi: str, user=Depends(auth_required)):
    supabase.table("store_settings").upsert({
        "store_id": user["store_id"],
        "upi_id": upi
    }).execute()

    return {"message": "UPI saved"}
