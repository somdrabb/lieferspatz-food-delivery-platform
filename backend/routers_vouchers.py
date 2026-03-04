from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from .database import get_session
from .deps import require_admin
from .models import Voucher, VoucherRedemption
from .schemas import VoucherCreate, VoucherOut, VoucherUpdate

router = APIRouter(prefix="/api/admin/vouchers", tags=["admin-vouchers"])


def _normalize_code(code: str) -> str:
    return code.strip().upper()


def _voucher_to_out(v: Voucher) -> VoucherOut:
    if isinstance(v.created_at, datetime):
        created_at = v.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        created_at = str(v.created_at)
    return VoucherOut(
        id=v.id,
        code=v.code,
        label=v.label,
        initial_balance_cents=v.initial_balance_cents,
        balance_cents=v.balance_cents,
        currency=v.currency,
        valid_from=v.valid_from,
        valid_until=v.valid_until,
        max_redemptions=v.max_redemptions,
        is_active=v.is_active,
        created_at=created_at,
    )


@router.get("", response_model=List[VoucherOut])
def list_vouchers(
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(Voucher).order_by(Voucher.created_at.desc())).all()
    return [_voucher_to_out(v) for v in rows]


@router.post("", response_model=VoucherOut, status_code=status.HTTP_201_CREATED)
def create_voucher(
    payload: VoucherCreate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    code = _normalize_code(payload.code)
    exists = session.exec(select(Voucher).where(Voucher.code == code)).first()
    if exists:
        raise HTTPException(status_code=400, detail="Voucher code already exists")

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    voucher = Voucher(
        code=code,
        label=payload.label,
        initial_balance_cents=max(0, payload.initial_balance_cents),
        balance_cents=max(0, payload.initial_balance_cents),
        currency="EUR",
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        max_redemptions=payload.max_redemptions,
        is_active=payload.is_active,
        created_at=now,
    )
    session.add(voucher)
    session.commit()
    session.refresh(voucher)
    return _voucher_to_out(voucher)


@router.get("/{voucher_id}", response_model=VoucherOut)
def get_voucher(
    voucher_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    voucher = session.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return _voucher_to_out(voucher)


@router.patch("/{voucher_id}", response_model=VoucherOut)
def update_voucher(
    voucher_id: int,
    payload: VoucherUpdate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    voucher = session.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    if payload.label is not None:
        voucher.label = payload.label
    if payload.balance_cents is not None:
        if payload.balance_cents < 0:
            raise HTTPException(status_code=400, detail="Balance cannot be negative")
        voucher.balance_cents = payload.balance_cents
    if payload.valid_from is not None:
        voucher.valid_from = payload.valid_from
    if payload.valid_until is not None:
        voucher.valid_until = payload.valid_until
    if payload.max_redemptions is not None:
        voucher.max_redemptions = payload.max_redemptions
    if payload.is_active is not None:
        voucher.is_active = payload.is_active

    session.add(voucher)
    session.commit()
    session.refresh(voucher)
    return _voucher_to_out(voucher)


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voucher(
    voucher_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    voucher = session.get(Voucher, voucher_id)
    if not voucher:
        return
    in_use = session.exec(select(VoucherRedemption).where(VoucherRedemption.voucher_id == voucher_id)).first()
    if in_use:
        raise HTTPException(status_code=409, detail="Voucher already redeemed; cannot delete")
    session.delete(voucher)
    session.commit()
