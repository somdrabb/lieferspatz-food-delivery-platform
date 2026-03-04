# backend/routers_auth.py

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi import status
from sqlmodel import Session, select
from sqlalchemy import func

from .database import get_session
from .models import Customer, Restaurant, WalletAccount
from .schemas import (
    LoginReq,
    Token,
    CustomerCreate,
    RestaurantCreate,
    RestaurantPasswordReset,
    RestaurantRegistrationResponse,
)
from .security import verify_password, hash_password, create_access_token
from .utils import log_event

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --------------------------------------------------------------------
# Helper: best-effort subject extraction from Authorization (optional)
# You can import/use this in other routers to read "sub" if present.
# --------------------------------------------------------------------
def get_optional_subject(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """
    Extracts the JWT 'sub' if an Authorization: Bearer ... header is present.
    Returns None if header/token is missing/invalid. This should be used as a
    soft dependency in public endpoints (do not raise here).
    """
    if not authorization:
        return None
    try:
        # We do NOT verify here, only decode to avoid raising on public endpoints.
        # Your create_access_token() already signs with HS256 and a secret.
        token = authorization.split(" ", 1)[1]
        # Lazy import to avoid hard-coding secrets here
        from .security import decode_token_unsafe  # implement as lightweight decode without verify
        payload = decode_token_unsafe(token)
        sub = payload.get("sub")
        return sub if isinstance(sub, str) else None
    except Exception:
        return None


# -----------------------
# Customer Authentication
# -----------------------

@router.post("/customer/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def customer_register(body: CustomerCreate, session: Session = Depends(get_session)):
    """
    Register a new customer, ensure they have a wallet, and return an access token.
    """
    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="Email is required")

    # Uniqueness check
    existing = session.exec(select(Customer).where(Customer.email == email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    cust = Customer(
        email=email,
        first_name=(body.first_name or "").strip(),
        last_name=(body.last_name or "").strip(),
        street=(body.street or "").strip(),
        postal_code=(body.postal_code or "").strip(),
        city=((body.city or "").strip() or None),
        phone=((body.phone or "").strip() or None),
        password_hash=hash_password(body.password),
    )
    session.add(cust)
    session.flush()  # get cust.id

    # Idempotent wallet creation
    acc = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == "customer",
            WalletAccount.ref_id == cust.id,
        )
    ).first()
    if not acc:
        session.add(
            WalletAccount(
                account_type="customer",
                ref_id=cust.id,
                balance_cents=10000,  # starter balance for dev
            )
        )

    session.commit()
    log_event(session, actor_type="customer", actor_id=cust.id, event="register", details={"email": cust.email})
    session.commit()
    return Token(access_token=create_access_token(f"customer:{cust.id}"))


@router.post("/customer/login", response_model=Token)
def customer_login(body: LoginReq, session: Session = Depends(get_session)):
    """
    Login by customer email + password.
    """
    email = (body.email_or_name or "").strip().lower()
    cust = session.exec(select(Customer).where(Customer.email == email)).first()
    if not cust or not verify_password(body.password or "", cust.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    log_event(session, actor_type="customer", actor_id=cust.id, event="login", details={})
    session.commit()
    return Token(access_token=create_access_token(f"customer:{cust.id}"))


# -------------------------
# Restaurant Authentication
# -------------------------

@router.post(
    "/restaurant/register",
    response_model=RestaurantRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def restaurant_register(body: RestaurantCreate, session: Session = Depends(get_session)):
    """Accept a lightweight application from a prospective restaurant owner."""
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    if not name:
        raise HTTPException(status_code=422, detail="Restaurant name is required")
    if not email:
        raise HTTPException(status_code=422, detail="Email is required")

    # Uniqueness checks (case-insensitive)
    exists_name = session.exec(
        select(Restaurant).where(func.lower(Restaurant.name) == name.lower())
    ).first()
    if exists_name:
        raise HTTPException(status_code=400, detail="Restaurant name already registered")
    exists_email = session.exec(
        select(Restaurant).where(func.lower(Restaurant.email) == email)
    ).first()
    if exists_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    password = (body.password or "").strip()
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="Password must be at least 4 characters")

    r = Restaurant(
        name=name,
        email=email,
        street="",
        postal_code="",
        description="",
        is_online=False,
        is_approved=False,
        password_hash=hash_password(password),
    )
    session.add(r)
    session.flush()  # r.id

    # Prepare wallet upfront so payouts work immediately after approval
    acc = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == "restaurant",
            WalletAccount.ref_id == r.id,
        )
    ).first()
    if not acc:
        session.add(
            WalletAccount(
                account_type="restaurant",
                ref_id=r.id,
                balance_cents=0,
            )
        )

    session.commit()
    log_event(
        session,
        actor_type="restaurant",
        actor_id=r.id,
        event="register",
        details={"name": r.name, "email": email, "approved": False},
    )
    session.commit()
    return RestaurantRegistrationResponse(
        status="pending",
        message="Application submitted. Our team will review and contact you once approved.",
    )


@router.post("/restaurant/login", response_model=Token)
def restaurant_login(body: LoginReq, session: Session = Depends(get_session)):
    """
    Login by restaurant email (preferred) or legacy name + password.
    """
    identifier = (body.email_or_name or "").strip().lower()
    candidate = (body.password or "")

    rest = None
    if identifier:
        rest = session.exec(
            select(Restaurant).where(func.lower(Restaurant.email) == identifier)
        ).first()
        if not rest:
            rest = session.exec(
                select(Restaurant).where(func.lower(Restaurant.name) == identifier)
            ).first()

    if not rest:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not rest.is_approved:
        raise HTTPException(status_code=403, detail="Application pending admin approval")

    # Accept exact or trimmed candidate
    pwd_ok = verify_password(candidate, rest.password_hash) or (
        candidate.strip() != candidate and verify_password(candidate.strip(), rest.password_hash)
    )
    if not pwd_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    log_event(session, actor_type="restaurant", actor_id=rest.id, event="login", details={})
    session.commit()
    return Token(access_token=create_access_token(f"restaurant:{rest.id}"))


@router.post("/restaurant/reset", response_model=dict)
def restaurant_reset_password(body: RestaurantPasswordReset, session: Session = Depends(get_session)):
    """
    Dev helper to reset a restaurant password without logging in.
    Protected by ADMIN_RESET_SECRET environment variable if set.
    """
    admin_secret = os.getenv("ADMIN_RESET_SECRET")
    if admin_secret and (body.secret or "") != admin_secret:
        raise HTTPException(status_code=403, detail="Invalid reset secret")

    name = (body.name or "").strip()
    rest = session.exec(
        select(Restaurant).where(func.lower(Restaurant.name) == name.lower())
    ).first()
    if not rest:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    new_pw = (body.new_password or "changeme").strip()
    if len(new_pw) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")

    rest.password_hash = hash_password(new_pw)
    session.add(rest)
    session.commit()
    log_event(session, actor_type="restaurant", actor_id=rest.id, event="password_reset", details={})
    session.commit()
    return {"ok": True}
