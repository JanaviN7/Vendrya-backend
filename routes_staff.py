from fastapi import APIRouter, Depends, HTTPException, Path
from datetime import datetime
from passlib.context import CryptContext
from pydantic import Field, BaseModel
from supabase_client import supabase
from auth.dependencies import auth_required

router = APIRouter(prefix="/staff", tags=["Staff"])

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)


# =======================
# SCHEMAS
# =======================

class StaffCreate(BaseModel):
    name: str
    role: str        # cashier | manager
    pin: str         # 4-digit PIN


class StaffLogin(BaseModel):
    name: str
    pin: str = Field(..., alias="pin_code")

    class Config:
        populate_by_name = True


class StaffStatusUpdate(BaseModel):
    status: str      # active | inactive


# =======================
# ADD STAFF (ADMIN ONLY)
# =======================

@router.post("/add")
def add_staff(payload: StaffCreate, user=Depends(auth_required)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin allowed")

    if payload.role not in ("cashier", "manager"):
        raise HTTPException(status_code=400, detail="Role must be cashier or manager")

    pin = payload.pin.strip()
    if len(pin) != 4 or not pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")

    staff = {
        "store_id": user["store_id"],
        "name": payload.name,
        "role": payload.role,
        "pin_hash": pwd_context.hash(pin),
        "status": "active",
        "last_activity": datetime.utcnow().isoformat()
    }

    res = supabase.table("store_users").insert(staff).execute()

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to add staff")

    return {"success": True, "staff": res.data[0]}


# =======================
# LIST STAFF (ADMIN ONLY)
# =======================

@router.get("")
def list_staff(user=Depends(auth_required)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin allowed")

    res = (
        supabase
        .table("store_users")
        .select("user_id,name,role,status,last_activity,created_at")
        .eq("store_id", user["store_id"])
        .neq("role", "admin")
        .order("created_at", desc=True)
        .execute()
    )

    return {
        "success": True,
        "count": len(res.data or []),
        "staff": res.data or []
    }


# =======================
# ACTIVATE / DEACTIVATE STAFF
# =======================

@router.patch("/{staff_id}/status")
def update_staff_status(
    staff_id: str = Path(...),
    payload: StaffStatusUpdate = None,
    user=Depends(auth_required)
):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin allowed")

    if not payload or payload.status not in ("active", "inactive"):
        raise HTTPException(status_code=400, detail="Status must be active or inactive")

    res = (
        supabase
        .table("store_users")
        .update({"status": payload.status})
        .eq("user_id", staff_id)
        .eq("store_id", user["store_id"])
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Staff not found")

    return {
        "success": True,
        "staff": res.data[0]
    }


# =======================
# STAFF LOGIN (PIN BASED)
# =======================

@router.post("/login")
def staff_login(payload: StaffLogin, user=Depends(auth_required)):
    res = (
        supabase
        .table("store_users")
        .select("*")
        .eq("store_id", user["store_id"])
        .eq("name", payload.name)
        .eq("status", "active")
        .single()
        .execute()
    )

    staff = res.data
    if not staff:
        raise HTTPException(401, "Invalid staff name or PIN")

    if not pwd_context.verify(payload.pin, staff["pin_hash"]):
        raise HTTPException(401, "Invalid staff name or PIN")

    supabase.table("store_users").update({
        "last_activity": datetime.utcnow().isoformat()
    }).eq("user_id", staff["user_id"]).execute()

    return {
        "success": True,
        "staff": {
            "user_id": staff["user_id"],
            "name": staff["name"],
            "role": staff["role"]
        }
    }
