from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .models import WalletAccount, WalletTxn
from .utils import log_event
from typing import List
from sqlmodel import Session, select
from .database import get_session
from .deps import get_current_subject

router = APIRouter(prefix="/api/wallet", tags=["wallet"])

@router.get("/me")
def my_wallet(sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind not in ("customer", "restaurant"):
        raise HTTPException(403, "Forbidden")
    wa = session.exec(select(WalletAccount).where(WalletAccount.account_type==kind, WalletAccount.ref_id==sid)).first()
    return {"account_type": kind, "ref_id": sid, "balance_cents": wa.balance_cents if wa else 0}

class TopupReq(BaseModel):
    amount_cents: int

@router.post("/topup")
def dev_topup(
    body: TopupReq,
    sub = Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    """
    Dev helper: add funds to *my* wallet (customer or restaurant).
    """
    if body.amount_cents <= 0:
        raise HTTPException(400, "amount_cents must be > 0")

    kind, sid = sub  # kind in {"customer","restaurant"}
    if kind not in {"customer", "restaurant"}:
        raise HTTPException(403, "Unsupported subject for topup")

    acc = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == kind,
            WalletAccount.ref_id == sid
        )
    ).first()
    if not acc:
        # Shouldn’t happen in your seed, but be defensive:
        acc = WalletAccount(account_type=kind, ref_id=sid, balance_cents=0)
        session.add(acc)
        session.commit()
        session.refresh(acc)

    acc.balance_cents += body.amount_cents
    session.add(WalletTxn(
        account_id=acc.id,
        amount_cents=body.amount_cents,
        reason="dev_topup",
        order_id=None,
    ))
    session.commit()
    session.refresh(acc)
    # audit
    log_event(session, actor_type=kind, actor_id=sid, event="wallet_topup", details={"amount_cents": body.amount_cents})
    session.commit()
    return {"ok": True, "new_balance_cents": acc.balance_cents}

@router.get("/txns")
def my_wallet_txns(
    limit: int = 20,
    sub = Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    acc = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == kind,
            WalletAccount.ref_id == sid
        )
    ).first()
    if not acc:
        raise HTTPException(404, "Wallet not found")

    q = (
        select(WalletTxn)
        .where(WalletTxn.account_id == acc.id)
        .order_by(WalletTxn.id.desc())
        .limit(limit)
    )
    return session.exec(q).all()
