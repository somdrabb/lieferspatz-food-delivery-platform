from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .database import get_session
from .deps import get_current_subject
from .models import Customer
from .schemas import CustomerOut, CustomerUpdate

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("/me", response_model=CustomerOut)
def get_me(
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(403, "Customer token required")
    cust = session.get(Customer, sid)
    if not cust:
        raise HTTPException(404, "Customer not found")
    return cust


@router.patch("/me", response_model=CustomerOut)
def update_me(
    payload: CustomerUpdate,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(403, "Customer token required")

    cust = session.get(Customer, sid)
    if not cust:
        raise HTTPException(404, "Customer not found")

    data = payload.dict(exclude_unset=True)

    if "email" in data and data["email"]:
        new_email = data["email"].strip().lower()
        if new_email != cust.email:
            exists = session.exec(
                select(Customer).where(Customer.email == new_email, Customer.id != cust.id)
            ).first()
            if exists:
                raise HTTPException(400, "Email already in use")
            cust.email = new_email

    for field in ["first_name", "last_name", "street", "postal_code"]:
        if field in data and data[field] is not None:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(cust, field, value)

    for field in ["city", "phone"]:
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(cust, field, value or None)

    session.add(cust)
    session.commit()
    session.refresh(cust)
    return cust
