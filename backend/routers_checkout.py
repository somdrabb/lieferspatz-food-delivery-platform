from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, text
from sqlmodel import Session, select

from .database import get_session
from .deps import get_current_subject
from .models import (
    Customer,
    CustomerAddress,
    DeliveryZip,
    MenuItem,
    Order,
    OrderItem,
    PaymentTxn,
    Restaurant,
    RestaurantNotification,
    Voucher,
    VoucherRedemption,
    WalletAccount,
    WalletTxn,
)
from .schemas import (
    CartItemPreview,
    CheckoutBreakdown,
    CheckoutPreviewOut,
    CheckoutResultOut,
    OrderCheckout,
    VoucherRedeemOut,
    VoucherRedeemRequest,
)
from .utils import log_event, now_iso, round_split, is_restaurant_open, generate_public_id
from .ws import manager


router = APIRouter(prefix="/api", tags=["checkout"])

CARD_LIKE_METHODS = {
    "card",
    "visa",
    "mastercard",
    "klarna",
    "apple_pay",
    "google_pay",
}


# ---------- helpers ----------

def _parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        # Accept trailing Z or offset-less strings
        cleaned = dt_str.replace("Z", "+00:00") if dt_str.endswith("Z") else dt_str
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _delivers_to(session: Session, rid: int, postal_code: str) -> bool:
    return (
        session.exec(
            select(DeliveryZip).where(
                DeliveryZip.restaurant_id == rid,
                DeliveryZip.postal_code == postal_code,
            )
        ).first()
        is not None
    )


def _require_customer(sub) -> Tuple[str, int]:
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer token required")
    return kind, sid


def _normalized_code(code: str) -> str:
    return (code or "").strip().upper()


def _load_customer(session: Session, customer_id: int) -> Customer:
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


def _load_restaurant(session: Session, rid: int) -> Restaurant:
    restaurant = session.get(Restaurant, rid)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


def _evaluate_voucher(
    session: Session,
    code: str,
    max_amount_cents: Optional[int],
) -> Tuple[Voucher, int]:
    voucher = session.exec(select(Voucher).where(Voucher.code == code)).first()
    if not voucher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voucher not found")

    if not voucher.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher inactive")

    now = datetime.utcnow()
    valid_from = _parse_iso(voucher.valid_from)
    if valid_from and now < valid_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher not yet valid")
    valid_until = _parse_iso(voucher.valid_until)
    if valid_until and now > valid_until:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher expired")

    if voucher.max_redemptions is not None:
        redeemed = session.exec(
            select(func.count(VoucherRedemption.id)).where(VoucherRedemption.voucher_id == voucher.id)
        ).one()
        redeemed_count = redeemed[0] if isinstance(redeemed, tuple) else redeemed
        if redeemed_count >= voucher.max_redemptions:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher usage limit reached")

    if voucher.balance_cents <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher depleted")

    if max_amount_cents is None:
        applied = voucher.balance_cents
    else:
        if max_amount_cents <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher amount must be positive")
        applied = min(voucher.balance_cents, max_amount_cents)
        if applied <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher amount not applicable")

    return voucher, applied


def _load_wallet(session: Session, customer_id: int) -> WalletAccount:
    wallet = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == "customer",
            WalletAccount.ref_id == customer_id,
        )
    ).first()
    if not wallet:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer wallet missing")
    return wallet


def _checkout_calculation(
    session: Session,
    customer: Customer,
    payload: OrderCheckout,
) -> Dict[str, object]:
    restaurant = _load_restaurant(session, payload.restaurant_id)
    if not restaurant.is_online:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant is currently offline")

    addr = payload.address
    postal_code = (addr.postal_code or "").strip()
    if not postal_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Postal code required")

    if not _delivers_to(session, restaurant.id, postal_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant does not deliver to this postal code")

    if not is_restaurant_open(session, restaurant.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant is closed right now")

    items_preview: List[CartItemPreview] = []
    subtotal = 0
    for raw in payload.items:
        if raw.quantity <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")
        menu_item = session.get(MenuItem, raw.menu_item_id)
        if not menu_item or menu_item.restaurant_id != restaurant.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid menu item in cart")
        line_total = menu_item.price_cents * raw.quantity
        subtotal += line_total
        items_preview.append(
            CartItemPreview(
                menu_item_id=menu_item.id,
                name=menu_item.name,
                price_cents=menu_item.price_cents,
                quantity=raw.quantity,
                line_total_cents=line_total,
            )
        )

    if not items_preview:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    if restaurant.min_order_cents and subtotal < restaurant.min_order_cents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum order is {(restaurant.min_order_cents or 0) / 100:.2f} €",
        )

    shipping_cents = restaurant.delivery_fee_cents or 0
    voucher = None
    voucher_amount = 0
    voucher_code = _normalized_code(payload.payment.voucher_code or "")
    if voucher_code:
        voucher, voucher_amount = _evaluate_voucher(session, voucher_code, subtotal + shipping_cents)

    total_after_voucher = max(subtotal + shipping_cents - voucher_amount, 0)

    payment_method = payload.payment.method
    payment_status = "pending"
    wallet_charge = 0
    payment_due = total_after_voucher

    if payment_method == "wallet":
        wallet = _load_wallet(session, customer.id)
        if wallet.balance_cents < total_after_voucher:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient wallet balance")
        wallet_charge = total_after_voucher
        payment_due = 0
        payment_status = "paid"
    elif payment_method == "voucher":
        if voucher_amount <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher required for voucher payment")
        if total_after_voucher > 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher does not cover full order total")
        payment_due = 0
        payment_status = "paid"
    elif payment_method in CARD_LIKE_METHODS:
        payment_status = "pending"
        # payment_due already set to total_after_voucher
    elif payment_method == "cash":
        payment_status = "pending"
        # payment_due already set to total_after_voucher
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported payment method")

    fee_platform_cents, payout_rest_cents = round_split(subtotal)

    breakdown = CheckoutBreakdown(
        subtotal_cents=subtotal,
        shipping_cents=shipping_cents,
        voucher_amount_cents=voucher_amount,
        total_cents=total_after_voucher,
        wallet_charge_cents=wallet_charge,
        payment_due_cents=payment_due,
    )

    return {
        "restaurant": restaurant,
        "items": items_preview,
        "voucher": voucher,
        "voucher_amount": voucher_amount,
        "breakdown": breakdown,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "fee_platform_cents": fee_platform_cents,
        "payout_rest_cents": payout_rest_cents,
    }


def _ensure_address(
    session: Session,
    customer: Customer,
    payload: OrderCheckout,
) -> Optional[CustomerAddress]:
    addr = payload.address
    normalized_fields = {
        "street": addr.street.strip(),
        "city": addr.city.strip(),
        "postal_code": addr.postal_code.strip(),
        "country": (addr.country or "DE").strip() or "DE",
    }

    existing = session.exec(
        select(CustomerAddress).where(
            CustomerAddress.customer_id == customer.id,
            CustomerAddress.street == normalized_fields["street"],
            CustomerAddress.city == normalized_fields["city"],
            CustomerAddress.postal_code == normalized_fields["postal_code"],
            CustomerAddress.country == normalized_fields["country"],
        )
    ).first()

    if existing:
        if addr.save_address and not existing.is_default:
            existing.is_default = True
        if addr.label is not None:
            existing.label = addr.label
        existing.phone = addr.phone or existing.phone
        existing.instructions = addr.instructions or existing.instructions
        session.add(existing)
        session.flush()
        return existing

    new_address = CustomerAddress(
        customer_id=customer.id,
        label=addr.label,
        street=normalized_fields["street"],
        city=normalized_fields["city"],
        postal_code=normalized_fields["postal_code"],
        country=normalized_fields["country"],
        phone=addr.phone,
        instructions=addr.instructions,
        is_default=addr.save_address,
    )
    session.add(new_address)
    session.flush()

    if addr.save_address:
        stmt = text(
            "UPDATE customeraddress "
            "SET is_default = CASE WHEN id = :new_id THEN 1 ELSE 0 END "
            "WHERE customer_id = :cid"
        )
        session.exec(stmt.bindparams(new_id=new_address.id, cid=customer.id))

    return new_address


def _wallet_account(session: Session, kind: str, ref_id: Optional[int]) -> WalletAccount:
    account = session.exec(
        select(WalletAccount).where(
            WalletAccount.account_type == kind,
            WalletAccount.ref_id == ref_id,
        )
    ).first()
    if not account:
        account = WalletAccount(account_type=kind, ref_id=ref_id, balance_cents=0)
        session.add(account)
        session.flush()
    return account


def _apply_wallet_transfers(
    session: Session,
    customer_wallet: WalletAccount,
    restaurant_wallet: WalletAccount,
    platform_wallet: WalletAccount,
    order: Order,
    wallet_charge: int,
    fee_platform_cents: int,
    payout_rest_cents: int,
) -> None:
    if wallet_charge <= 0:
        return

    customer_wallet.balance_cents -= wallet_charge
    session.add(
        WalletTxn(
            account_id=customer_wallet.id,
            amount_cents=-wallet_charge,
            reason="order_charge",
            order_id=order.id,
        )
    )

    platform_wallet.balance_cents += fee_platform_cents
    session.add(
        WalletTxn(
            account_id=platform_wallet.id,
            amount_cents=fee_platform_cents,
            reason="order_fee_platform",
            order_id=order.id,
        )
    )

    restaurant_wallet.balance_cents += payout_rest_cents
    session.add(
        WalletTxn(
            account_id=restaurant_wallet.id,
            amount_cents=payout_rest_cents,
            reason="order_payout_restaurant",
            order_id=order.id,
        )
    )


# ---------- endpoints ----------


@router.post("/cart/preview", response_model=CheckoutPreviewOut)
def preview_checkout(
    payload: OrderCheckout,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    _, sid = _require_customer(sub)
    customer = _load_customer(session, sid)
    data = _checkout_calculation(session, customer, payload)

    return CheckoutPreviewOut(
        restaurant_id=data["restaurant"].id,
        restaurant_name=data["restaurant"].name,
        items=data["items"],
        breakdown=data["breakdown"],
    )


@router.post("/checkout", response_model=CheckoutResultOut, status_code=status.HTTP_201_CREATED)
def submit_checkout(
    payload: OrderCheckout,
    background_tasks: BackgroundTasks,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    _, sid = _require_customer(sub)
    customer = _load_customer(session, sid)
    data = _checkout_calculation(session, customer, payload)

    address = _ensure_address(session, customer, payload)

    order = Order(
        customer_id=customer.id,
        restaurant_id=data["restaurant"].id,
        address_id=address.id if address else None,
        voucher_id=data["voucher"].id if data["voucher"] else None,
        status="in_bearbeitung",
        payment_status=data["payment_status"],
        payment_method=data["payment_method"],
        note_for_kitchen=payload.note_for_kitchen or "",
        subtotal_cents=data["breakdown"].subtotal_cents,
        shipping_cents=data["breakdown"].shipping_cents,
        voucher_amount_cents=data["breakdown"].voucher_amount_cents,
        total_cents=data["breakdown"].total_cents,
        fee_platform_cents=data["fee_platform_cents"],
        payout_rest_cents=data["payout_rest_cents"],
        public_id=generate_public_id(session, Order, "public_id", prefix="ORD"),
    )
    session.add(order)
    session.flush()

    for item in data["items"]:
        session.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=item.menu_item_id,
                name_snapshot=item.name,
                price_cents_snapshot=item.price_cents,
                quantity=item.quantity,
            )
        )

    if data["voucher"]:
        voucher = data["voucher"]
        voucher.balance_cents = max(
            0, voucher.balance_cents - data["breakdown"].voucher_amount_cents
        )
        if voucher.balance_cents <= 0:
            voucher.is_active = False
        session.add(voucher)
        session.add(
            VoucherRedemption(
                voucher_id=voucher.id,
                order_id=order.id,
                amount_cents=data["breakdown"].voucher_amount_cents,
            )
        )
        session.add(
            PaymentTxn(
                order_id=order.id,
                provider="voucher",
                provider_ref=voucher.code,
                amount_cents=data["breakdown"].voucher_amount_cents,
                currency=voucher.currency,
                status="settled",
            )
        )

    wallet_charge = data["breakdown"].wallet_charge_cents
    payment_due = data["breakdown"].payment_due_cents

    if data["payment_method"] == "wallet" and wallet_charge > 0:
        customer_wallet = _load_wallet(session, customer.id)
        restaurant_wallet = _wallet_account(session, "restaurant", data["restaurant"].id)
        platform_wallet = _wallet_account(session, "platform", None)
        _apply_wallet_transfers(
            session,
            customer_wallet,
            restaurant_wallet,
            platform_wallet,
            order,
            wallet_charge,
            data["fee_platform_cents"],
            data["payout_rest_cents"],
        )
        session.add(
            PaymentTxn(
                order_id=order.id,
                provider="wallet",
                provider_ref=str(customer_wallet.id),
                amount_cents=wallet_charge,
                currency="EUR",
                status="settled",
            )
        )
    elif data["payment_method"] in {"card", "cash"} and payment_due > 0:
        session.add(
            PaymentTxn(
                order_id=order.id,
                provider=data["payment_method"],
                amount_cents=payment_due,
                currency="EUR",
                status="pending",
            )
        )

    session.add(
        RestaurantNotification(restaurant_id=data["restaurant"].id, order_id=order.id, type="new_order")
    )
    session.flush()

    log_event(
        session,
        actor_type="customer",
        actor_id=customer.id,
        event="order_created",
        details={
            "order_id": order.id,
            "restaurant_id": data["restaurant"].id,
            "total_cents": data["breakdown"].total_cents,
            "payment_method": data["payment_method"],
        },
    )
    session.commit()

    background_tasks.add_task(
        manager.broadcast,
        data["restaurant"].id,
        {
            "type": "new_order",
            "order_id": order.id,
            "created_at": order.created_at,
            "total_cents": order.total_cents,
        },
    )

    return CheckoutResultOut(
        order_id=order.id,
        order_status=order.status,
        payment_status=order.payment_status,
        restaurant_id=data["restaurant"].id,
        restaurant_name=data["restaurant"].name,
        items=data["items"],
        breakdown=data["breakdown"],
    )


@router.post("/vouchers/redeem", response_model=VoucherRedeemOut)
def preview_voucher_redemption(
    payload: VoucherRedeemRequest,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    _require_customer(sub)
    code = _normalized_code(payload.code)
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher code required")

    amount_hint = payload.amount_cents if payload.amount_cents and payload.amount_cents > 0 else None
    voucher, preview_amount = _evaluate_voucher(session, code, amount_hint)

    if payload.amount_cents:
        applied = min(preview_amount, payload.amount_cents)
        if applied <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Requested amount not available")
        remaining = voucher.balance_cents - applied
    else:
        applied = 0
        remaining = voucher.balance_cents

    return VoucherRedeemOut(
        voucher_id=voucher.id,
        code=voucher.code,
        label=voucher.label,
        applied_amount_cents=applied,
        available_balance_cents=voucher.balance_cents,
        remaining_balance_cents=max(remaining, 0),
        currency=voucher.currency,
        valid_from=voucher.valid_from,
        valid_until=voucher.valid_until,
    )
