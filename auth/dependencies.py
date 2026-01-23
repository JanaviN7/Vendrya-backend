from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import config

security = HTTPBearer(auto_error=False)


def auth_required(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    # Allow CORS preflight
    if request.method == "OPTIONS":
        return None

    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization token missing")

    try:
        payload = jwt.decode(
            credentials.credentials,
            config.JWT_SECRET,
            algorithms=["HS256"]
        )

        return {
            "user_id": payload["user_id"],
            "store_id": payload["store_id"],
            "role": payload.get("role", "staff"),
            "email": payload.get("email")
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    