from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from supabase_client import supabase
from auth.dependencies import auth_required     # your existing dependency

router = APIRouter(prefix="/staff", tags=["Staff"])

class StaffCreate(BaseModel):
    name: str
    email: EmailStr
    role: str  # 'cashier' or 'manager' etc.

@router.post("/add")
def add_staff(payload: StaffCreate, user=Depends(auth_required)):
    store_id = user["store_id"]
    # optional: check role validity
    if payload.role not in ("cashier","manager","admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    # create record (store_id to scope it)
    res = supabase.table("store_users").insert({
        "store_id": store_id,
        "name": payload.name,
        "email": payload.email,
        "role": payload.role,
        "status": "active"
    }).execute()

    if not getattr(res, "data", None):
        raise HTTPException(status_code=500, detail="Failed to create staff")

    return {"message": "Staff added", "user": res.data[0]}
