# backend/security.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from jose import jwt
from passlib.context import CryptContext

# --------------------------------------------------------------------
# JWT settings
# --------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))
ISSUER = os.environ.get("JWT_ISSUER", "lieferspatz-api")  # optional; not enforced on decode

# --------------------------------------------------------------------
# Password hashing (bcrypt via passlib)
# --------------------------------------------------------------------
_pwd_ctx = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)

def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    """
    if not isinstance(password, str) or password == "":
        raise ValueError("Password must be a non-empty string")
    return _pwd_ctx.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    """
    try:
        return _pwd_ctx.verify(password or "", password_hash or "")
    except Exception:
        return False

# --------------------------------------------------------------------
# JWT helpers
# --------------------------------------------------------------------
def create_access_token(subject: str, expires_delta: Optional[timedelta] = None, extra: Optional[Dict[str, Any]] = None) -> str:
    """
    Create a signed JWT access token carrying a string 'sub' (e.g. 'customer:42').
    """
    if not subject or not isinstance(subject, str):
        raise ValueError("subject must be a non-empty string")

    now = datetime.now(timezone.utc)
    exp = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": ISSUER,
    }
    if extra:
        # Avoid overwriting reserved claims accidentally
        for k, v in extra.items():
            if k not in {"sub", "iat", "nbf", "exp", "iss"}:
                payload[k] = v

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token_unsafe(token: str) -> Dict[str, Any]:
    """
    Return claims from a JWT **without** verifying the signature.
    Use ONLY for optional, non-authz flows (e.g., showing who might be logged in).
    Do not rely on this to authorize any action.

    With python-jose, use get_unverified_claims rather than a verified decode.
    """
    try:
        return jwt.get_unverified_claims(token)  # type: ignore[no-any-return]
    except Exception:
        # Always return a dict for callers; empty indicates failure.
        return {}

# (Optional) If you need a strict decode anywhere else:
def decode_token_strict(token: str) -> Dict[str, Any]:
    """
    Decode & verify signature/exp; raise on invalid tokens.
    Useful for protected endpoints when you don’t use a dependency layer.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_aud": False})
