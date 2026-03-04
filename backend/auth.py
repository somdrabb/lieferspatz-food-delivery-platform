# backend/auth.py
from __future__ import annotations
import os
from typing import Optional
from fastapi import Header, HTTPException, Depends
from jose import jwt, JWTError  # or whatever you use in create_access_token

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")  # same one used in create_access_token
JWT_ALG = os.getenv("JWT_ALG", "HS256")

def _allow_by_header(x_admin_token: Optional[str]) -> bool:
    return x_admin_token == ADMIN_TOKEN

def _allow_by_jwt(authz: Optional[str]) -> bool:
    if not authz or not authz.lower().startswith("bearer "):
        return False
    token = authz.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        return False
    sub = (payload or {}).get("sub") or ""
    return isinstance(sub, str) and sub.startswith("admin:")

def require_admin(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if _allow_by_header(x_admin_token) or _allow_by_jwt(authorization):
        return "ok"
    raise HTTPException(status_code=401, detail="Admin token required")
