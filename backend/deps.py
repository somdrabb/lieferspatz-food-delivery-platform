from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from .security import SECRET_KEY, ALGORITHM

bearer = HTTPBearer(auto_error=False)


def parse_subject(sub: str):
    parts = sub.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(401, "Invalid token")
    kind, raw_sid = parts
    if kind in {"customer", "restaurant"}:
        try:
            return kind, int(raw_sid)
        except ValueError:
            raise HTTPException(401, "Invalid token")
    return kind, raw_sid


def get_current_subject(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds:
        raise HTTPException(401, "Not authenticated")
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(401, "Invalid token")
        return parse_subject(sub)
    except JWTError:
        raise HTTPException(401, "Invalid token")


def require_admin(sub=Depends(get_current_subject)):
    kind, _ = sub
    if kind != "admin":
        raise HTTPException(403, "Admin access required")
    return sub[1]
