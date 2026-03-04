# backend/routers_admin.py
from __future__ import annotations

import os
import json
import random
import string
import re
from io import BytesIO
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Response
from sqlalchemy import func
from sqlmodel import Session, select, delete, SQLModel, Field

from .database import get_session
from .auth import require_admin
from .security import create_access_token, hash_password, verify_password
from .utils import log_event, generate_public_id, now_iso

# Models
from .models import (
    Voucher,
    VoucherRedemption,
    Restaurant,
    MenuItem,
    OpeningHour,
    DeliveryZip,
    Order,
    OrderItem,
    OrderEvent,
    PaymentTxn,
    RestaurantNotification,
    WalletAccount,
    WalletTxn,
    DeletedRestaurant,
    DeletedOrder,
    GdprRequest,
)

# Schemas
from .schemas import (
    LoginReq,
    Token,
    RestaurantDetailOut,
    AdminRestaurantCreate,
    AdminRestaurantUpdate,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ---------------------------------------------------------------------
# Local response models
# ---------------------------------------------------------------------


class DeletedRestaurantOut(SQLModel):
    id: int
    restaurant_public_id: str
    name: str
    deleted_at: str
    reason: Optional[str] = None
    deleted_by: Optional[str] = None
    extra: Dict[str, Any]


class DeleteRestaurantPayload(SQLModel):
    reason: Optional[str] = None
    deleted_by: Optional[str] = None


class GdprRequestCreate(SQLModel):
    requester_type: str
    requester_id: Optional[int] = None
    requester_email: Optional[str] = None
    request_type: str
    details: Optional[str] = None


class GdprRequestUpdate(SQLModel):
    status: Optional[str] = None
    processed_by: Optional[str] = None
    resolution_notes: Optional[str] = None


class GdprRequestOut(SQLModel):
    id: int
    requester_type: str
    requester_id: Optional[int] = None
    requester_email: Optional[str] = None
    request_type: str
    status: str
    details: Optional[str] = None
    created_at: str
    updated_at: str
    processed_at: Optional[str] = None
    processed_by: Optional[str] = None
    resolution_notes: Optional[str] = None


class InvoiceItemOut(SQLModel):
    name: str
    quantity: int
    price_cents: int
    line_total_cents: int


class InvoiceOrderSummary(SQLModel):
    order_id: int
    order_public_id: Optional[str] = None
    restaurant_name: Optional[str] = None
    restaurant_public_id: Optional[str] = None
    total_cents: int
    created_at: str


class InvoiceReceiptOut(SQLModel):
    order_id: int
    order_public_id: Optional[str] = None
    customer_id: Optional[int] = None
    restaurant_name: Optional[str] = None
    restaurant_public_id: Optional[str] = None
    created_at: str
    subtotal_cents: int
    shipping_cents: int
    voucher_amount_cents: int
    total_cents: int
    payment_method: Optional[str] = None
    items: List[InvoiceItemOut] = Field(default_factory=list)


class InvoiceMonthSummary(SQLModel):
    month: str
    order_count: int
    total_cents: int
    shipping_cents: int
    voucher_cents: int
    fee_platform_cents: int
    payout_rest_cents: int

# ---------------------------------------------------------------------
# Admin credentials (login)
# ---------------------------------------------------------------------
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin34024742@gmail.com").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin34024742")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")


def _verify_admin_credentials(email: str, password: str) -> bool:
    if email.strip().lower() != ADMIN_EMAIL:
        return False
    candidate = (password or "").strip()
    if ADMIN_PASSWORD_HASH:
        try:
            return verify_password(candidate, ADMIN_PASSWORD_HASH)
        except Exception:
            return False
    return candidate == ADMIN_PASSWORD


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _restaurant_detail(session: Session, rid: int) -> RestaurantDetailOut:
    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    menu = session.exec(select(MenuItem).where(MenuItem.restaurant_id == rid)).all()
    hours = session.exec(select(OpeningHour).where(OpeningHour.restaurant_id == rid)).all()
    zips = session.exec(select(DeliveryZip).where(DeliveryZip.restaurant_id == rid)).all()

    return {"restaurant": r, "menu": menu, "opening_hours": hours, "delivery_zips": zips}


def _delete_restaurant(
    session: Session,
    rid: int,
    *,
    force: bool = False,
    reason: Optional[str] = None,
    deleted_by: Optional[str] = None,
) -> None:
    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    order_ids = list(session.exec(select(Order.id).where(Order.restaurant_id == rid)))
    if order_ids and not force:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete restaurant with existing orders. Use force=true to override.",
        )

    if order_ids:
        session.exec(delete(VoucherRedemption).where(VoucherRedemption.order_id.in_(order_ids)))
        session.exec(delete(PaymentTxn).where(PaymentTxn.order_id.in_(order_ids)))
        session.exec(delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids)))
        session.exec(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        session.exec(delete(RestaurantNotification).where(RestaurantNotification.order_id.in_(order_ids)))
        session.exec(delete(Order).where(Order.id.in_(order_ids)))

    acc_ids = list(
        session.exec(
            select(WalletAccount.id).where(
                WalletAccount.account_type == "restaurant",
                WalletAccount.ref_id == rid,
            )
        )
    )
    if acc_ids:
        session.exec(delete(WalletTxn).where(WalletTxn.account_id.in_(acc_ids)))
        session.exec(delete(WalletAccount).where(WalletAccount.id.in_(acc_ids)))

    session.exec(delete(MenuItem).where(MenuItem.restaurant_id == rid))
    session.exec(delete(OpeningHour).where(OpeningHour.restaurant_id == rid))
    session.exec(delete(DeliveryZip).where(DeliveryZip.restaurant_id == rid))

    snapshot = {
        "street": r.street,
        "postal_code": r.postal_code,
        "city": r.city,
        "created_at": r.created_at,
        "is_demo": r.is_demo,
        "deleted_with_force": bool(force),
    }
    if reason:
        snapshot["reason"] = reason
    if deleted_by:
        snapshot["deleted_by"] = deleted_by
    session.add(
        DeletedRestaurant(
            original_restaurant_id=r.id,
            restaurant_public_id=r.public_id or f"RST-LEGACY-{r.id}",
            name=r.name,
            reason=reason,
            deleted_by=deleted_by,
            extra_json=json.dumps(snapshot),
        )
    )

    session.delete(r)
    session.commit()


# ---------------------------------------------------------------------
# Helpers: GDPR & invoices
# ---------------------------------------------------------------------


def _normalize_requester_type(value: Optional[str]) -> str:
    candidate = (value or "customer").strip().lower()
    if candidate.startswith("rest"):
        return "restaurant"
    if candidate.startswith("cust"):
        return "customer"
    if candidate in {"platform", "admin", "support"}:
        return "platform"
    return candidate or "customer"


def _normalize_request_type(value: Optional[str]) -> str:
    candidate = (value or "export").strip().lower()
    if candidate in {"delete", "erasure", "removal"}:
        return "deletion"
    if candidate in {"export", "access", "copy"}:
        return "export"
    return "export"


def _gdpr_to_out(entry: GdprRequest) -> GdprRequestOut:
    return GdprRequestOut(
        id=entry.id,
        requester_type=entry.requester_type,
        requester_id=entry.requester_id,
        requester_email=entry.requester_email,
        request_type=entry.request_type,
        status=entry.status,
        details=entry.details,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        processed_at=entry.processed_at,
        processed_by=entry.processed_by,
        resolution_notes=entry.resolution_notes,
    )


def _make_invoice_summary(order: Order, restaurant: Optional[Restaurant]) -> InvoiceOrderSummary:
    return InvoiceOrderSummary(
        order_id=order.id,
        order_public_id=order.public_id,
        restaurant_name=restaurant.name if restaurant else None,
        restaurant_public_id=restaurant.public_id if restaurant else None,
        total_cents=order.total_cents or 0,
        created_at=order.created_at,
    )


def _make_invoice_receipt(order: Order) -> InvoiceReceiptOut:
    session_items = getattr(order, "items", []) or []
    items = [
        InvoiceItemOut(
            name=item.name_snapshot,
            quantity=item.quantity,
            price_cents=item.price_cents_snapshot,
            line_total_cents=item.price_cents_snapshot * item.quantity,
        )
        for item in session_items
    ]
    restaurant = getattr(order, "restaurant", None)
    return InvoiceReceiptOut(
        order_id=order.id,
        order_public_id=order.public_id,
        customer_id=order.customer_id,
        restaurant_name=restaurant.name if restaurant else None,
        restaurant_public_id=restaurant.public_id if restaurant else None,
        created_at=order.created_at,
        subtotal_cents=order.subtotal_cents or 0,
        shipping_cents=order.shipping_cents or 0,
        voucher_amount_cents=order.voucher_amount_cents or 0,
        total_cents=order.total_cents or 0,
        payment_method=order.payment_method,
        items=items,
    )


def _format_euro(cents: int) -> str:
    return f"{(cents or 0) / 100:.2f}"


def _receipt_to_csv(receipt: InvoiceReceiptOut) -> str:
    lines = [
        "Item,Quantity,Unit (EUR),Line Total (EUR)",
    ]
    for item in receipt.items:
        lines.append(
            f"{item.name.replace(',', ' ')},{item.quantity},{_format_euro(item.price_cents)},{_format_euro(item.line_total_cents)}"
        )
    lines.append("")
    lines.append(f"Subtotal,,,{_format_euro(receipt.subtotal_cents)}")
    lines.append(f"Shipping,,,{_format_euro(receipt.shipping_cents)}")
    lines.append(f"Voucher,,,-{_format_euro(receipt.voucher_amount_cents)}")
    lines.append(f"Total,,,{_format_euro(receipt.total_cents)}")
    return "\n".join(lines)


def _monthly_summary_to_csv(month: str, rows: List[InvoiceOrderSummary], totals: InvoiceMonthSummary) -> str:
    header = [
        f"Invoice summary for {month}",
        "Order ID,Order Public ID,Restaurant,Total (EUR),Created At",
    ]
    body = [
        f"{row.order_id},{row.order_public_id or ''},{(row.restaurant_name or '').replace(',', ' ')},{_format_euro(row.total_cents)},{row.created_at}"
        for row in rows
    ]
    footer = [
        "",
        f"Order count,,,{totals.order_count},",
        f"Gross revenue,,,{_format_euro(totals.total_cents)},",
        f"Shipping collected,,,{_format_euro(totals.shipping_cents)},",
        f"Voucher discounts,,,-{_format_euro(totals.voucher_cents)},",
        f"Platform fees,,,{_format_euro(totals.fee_platform_cents)},",
        f"Restaurant payouts,,,{_format_euro(totals.payout_rest_cents)},",
    ]
    return "\n".join(header + body + footer)


def _escape_pdf_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _lines_to_pdf(lines: List[str], title: str) -> bytes:
    width, height = 595, 842  # A4 in points
    top_margin = height - 60
    leading = 18

    safe_lines = [_escape_pdf_text(line) for line in lines]
    title_safe = _escape_pdf_text(title)

    contents = ["BT", "/F1 16 Tf", f"1 0 0 1 40 {top_margin} Tm ({title_safe}) Tj", "/F1 12 Tf"]
    y = top_margin - 30
    for line in safe_lines:
        if y < 60:
            # simple page overflow guard: add blank line indicator
            contents.append(f"1 0 0 1 40 60 Tm ({_escape_pdf_text('... output truncated ...')}) Tj")
            break
        contents.append(f"1 0 0 1 40 {y} Tm ({line}) Tj")
        y -= leading
    contents.append("ET")
    stream_bytes = "\n".join(contents).encode("utf-8")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    contents_obj = (
        f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("utf-8")
        + stream_bytes
        + b"\nendstream"
    )
    objects.append(contents_obj)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("utf-8"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")
    xref_start = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(f"{offset:010} 00000 n \n".encode("utf-8"))
    buffer.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode("utf-8")
    )
    return buffer.getvalue()


def _receipt_to_pdf(receipt: InvoiceReceiptOut) -> bytes:
    lines = [
        f"Order: {receipt.order_public_id or receipt.order_id}",
        f"Restaurant: {receipt.restaurant_name or 'n/a'}",
        f"Restaurant ID: {receipt.restaurant_public_id or 'n/a'}",
        f"Customer ID: {receipt.customer_id or 'n/a'}",
        f"Created at: {receipt.created_at}",
        f"Payment method: {receipt.payment_method or 'n/a'}",
        "",
        "Items:",
    ]
    if receipt.items:
        for item in receipt.items:
            lines.append(
                f" - {item.quantity} x {item.name} @ EUR {_format_euro(item.price_cents)}"
            )
    else:
        lines.append(" - (no items)")
    lines.extend(
        [
            "",
            f"Subtotal: EUR {_format_euro(receipt.subtotal_cents)}",
            f"Shipping: EUR {_format_euro(receipt.shipping_cents)}",
            f"Voucher: -EUR {_format_euro(receipt.voucher_amount_cents)}",
            f"Total: EUR {_format_euro(receipt.total_cents)}",
        ]
    )
    return _lines_to_pdf(lines, "Lieferspatz Order Receipt")


def _monthly_summary_to_pdf(month: str, rows: List[InvoiceOrderSummary], totals: InvoiceMonthSummary) -> bytes:
    lines = [
        f"Month: {month}",
        "",
        f"Orders: {totals.order_count}",
        f"Gross revenue: EUR {_format_euro(totals.total_cents)}",
        f"Shipping collected: EUR {_format_euro(totals.shipping_cents)}",
        f"Voucher discounts: EUR {_format_euro(totals.voucher_cents)}",
        f"Platform fees: EUR {_format_euro(totals.fee_platform_cents)}",
        f"Restaurant payouts: EUR {_format_euro(totals.payout_rest_cents)}",
        "",
        "Orders:",
    ]
    if rows:
        for row in rows:
            lines.append(
                f" - {row.order_public_id or row.order_id}: {row.restaurant_name or 'n/a'} · EUR {_format_euro(row.total_cents)} · {row.created_at}"
            )
    else:
        lines.append(" - (no orders)")

    return _lines_to_pdf(lines, "Lieferspatz Monthly Summary")


# ---------------------------------------------------------------------
# Routes: Admin login
# ---------------------------------------------------------------------
@router.post("/login", response_model=Token)
def admin_login(body: LoginReq, session: Session = Depends(get_session)):
    if not _verify_admin_credentials(body.email_or_name, body.password):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    # Audit
    log_event(
        session,
        actor_type="admin",
        actor_id=None,
        event="login",
        details={"email": body.email_or_name.strip().lower()},
    )
    session.commit()

    return Token(access_token=create_access_token(f"admin:{ADMIN_EMAIL}"))


# ---------------------------------------------------------------------
# Routes: Restaurants
# ---------------------------------------------------------------------
@router.get("/restaurants", response_model=List[RestaurantDetailOut])
def admin_list_restaurants(
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(Restaurant.id).order_by(Restaurant.name)).all()
    return [_restaurant_detail(session, rid) for rid in rows]


@router.get("/restaurants/{rid}", response_model=RestaurantDetailOut)
def admin_restaurant_detail(
    rid: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return _restaurant_detail(session, rid)


@router.post("/restaurants", response_model=RestaurantDetailOut, status_code=status.HTTP_201_CREATED)
def admin_create_restaurant(
    payload: AdminRestaurantCreate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    name = payload.name.strip()
    exists = session.exec(
        select(Restaurant).where(func.lower(Restaurant.name) == name.lower())
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Restaurant name already registered")

    email = (payload.email or "").strip().lower() if payload.email else None
    if email:
        email_exists = session.exec(
            select(Restaurant).where(func.lower(Restaurant.email) == email)
        ).first()
        if email_exists:
            raise HTTPException(status_code=400, detail="Email already registered")

    r = Restaurant(
        name=name,
        email=email,
        street=payload.street.strip(),
        postal_code=payload.postal_code.strip(),
        description=payload.description.strip(),
        image_url=(payload.image_url or None),
        city=(payload.city.strip() if payload.city else None),
        min_order_cents=payload.min_order_cents or 0,
        delivery_fee_cents=payload.delivery_fee_cents or 0,
        prep_time_min=payload.prep_time_min or 20,
        is_online=payload.is_online if payload.is_online is not None else True,
        is_approved=payload.is_approved if payload.is_approved is not None else True,
        is_demo=payload.is_demo if payload.is_demo is not None else False,
        busy_until=payload.busy_until.strip() if payload.busy_until else None,
        extra=payload.extra or None,
        password_hash=hash_password(payload.password),
        public_id=generate_public_id(session, Restaurant, "public_id", prefix="RST"),
    )
    if not r.is_approved:
        r.is_online = False
    session.add(r)
    session.commit()
    session.refresh(r)

    if payload.delivery_zips is not None:
        for pc in payload.delivery_zips:
            pc_val = (pc or "").strip()
            if pc_val:
                session.add(DeliveryZip(restaurant_id=r.id, postal_code=pc_val))

    if payload.opening_hours is not None:
        for oh in payload.opening_hours:
            session.add(
                OpeningHour(
                    restaurant_id=r.id,
                    weekday=oh.weekday,
                    open_time=oh.open_time,
                    close_time=oh.close_time,
                )
            )
    session.commit()

    log_event(session, actor_type="admin", actor_id=None, event="restaurant_create", details={"restaurant_id": r.id})
    session.commit()
    return _restaurant_detail(session, r.id)


@router.patch("/restaurants/{rid}", response_model=RestaurantDetailOut)
def admin_update_restaurant(
    rid: int,
    payload: AdminRestaurantUpdate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    data = payload.dict(exclude_unset=True)
    delivery_zips = data.pop("delivery_zips", None)
    opening_hours = data.pop("opening_hours", None)
    extra = data.pop("extra", None)
    password = data.pop("password", None)

    email = data.pop("email", None)
    if email is not None:
        email_norm = email.strip().lower()
        if email_norm:
            exists_email = session.exec(
                select(Restaurant).where(
                    func.lower(Restaurant.email) == email_norm,
                    Restaurant.id != rid,
                )
            ).first()
            if exists_email:
                raise HTTPException(status_code=400, detail="Email already registered")
            r.email = email_norm
        else:
            r.email = None

    if "is_approved" in data:
        raw_flag = data.pop("is_approved")
        if isinstance(raw_flag, str):
            flag_norm = raw_flag.strip().lower()
            flag_value = flag_norm in {"1", "true", "yes", "on"}
        else:
            flag_value = bool(raw_flag)
        previously = r.is_approved
        r.is_approved = flag_value
        if not r.is_approved:
            r.is_online = False
        if r.is_approved and not previously and not r.public_id:
            r.public_id = generate_public_id(session, Restaurant, "public_id", prefix="RST")

    # unique name check
    name = data.get("name")
    if name and name.strip() != r.name:
        exists = session.exec(
            select(Restaurant).where(
                func.lower(Restaurant.name) == name.strip().lower(),
                Restaurant.id != rid,
            )
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="Restaurant name already registered")
        r.name = name.strip()

    for field in [
        "street",
        "city",
        "postal_code",
        "description",
        "image_url",
        "min_order_cents",
        "delivery_fee_cents",
        "prep_time_min",
        "is_online",
        "is_demo",
        "busy_until",
        "is_approved",
    ]:
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            if field in {"min_order_cents", "delivery_fee_cents", "prep_time_min"} and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{field} must be an integer")
            setattr(r, field, value)

    if extra is not None:
        r.extra = extra or {}

    if password:
        r.password_hash = hash_password(password)

    if delivery_zips is not None:
        session.exec(delete(DeliveryZip).where(DeliveryZip.restaurant_id == rid))
        for pc in delivery_zips or []:
            pc_val = (pc or "").strip()
            if pc_val:
                session.add(DeliveryZip(restaurant_id=rid, postal_code=pc_val))

    if opening_hours is not None:
        session.exec(delete(OpeningHour).where(OpeningHour.restaurant_id == rid))
        for oh in opening_hours or []:
            d = oh if isinstance(oh, dict) else oh.dict()
            session.add(
                OpeningHour(
                    restaurant_id=rid,
                    weekday=d["weekday"],
                    open_time=d["open_time"],
                    close_time=d["close_time"],
                )
            )

    session.add(r)
    session.commit()
    session.refresh(r)

    log_event(session, actor_type="admin", actor_id=None, event="restaurant_update", details={"restaurant_id": r.id})
    session.commit()
    return _restaurant_detail(session, r.id)


@router.post("/restaurants/{rid}/approve", response_model=RestaurantDetailOut)
def admin_approve_restaurant(
    rid: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    changed = False
    if not r.is_approved:
        r.is_approved = True
        changed = True
    if not r.public_id:
        r.public_id = generate_public_id(session, Restaurant, "public_id", prefix="RST")
        changed = True
    if changed:
        session.add(r)
        session.commit()
        session.refresh(r)
        log_event(session, actor_type="admin", actor_id=None, event="restaurant_approve", details={"restaurant_id": r.id})
        session.commit()
    return _restaurant_detail(session, r.id)


@router.delete("/restaurants/{rid}")
def admin_delete_restaurant(
    rid: int,
    force: Optional[bool] = False,
    payload: Optional[DeleteRestaurantPayload] = Body(default=None),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    reason = (payload.reason if payload else None) or None
    deleted_by = (payload.deleted_by if payload else None) or None
    _delete_restaurant(session, rid, force=bool(force), reason=reason, deleted_by=deleted_by)
    log_event(
        session,
        actor_type="admin",
        actor_id=None,
        event="restaurant_delete",
        details={"restaurant_id": rid, "reason": reason, "deleted_by": deleted_by, "force": bool(force)},
    )
    session.commit()
    return {"ok": True}


@router.get("/restaurants/deleted", response_model=List[DeletedRestaurantOut])
def admin_list_deleted_restaurants(
    q: Optional[str] = Query(default=None, description="Filter by archived/public id or name"),
    limit: int = Query(default=200, ge=1, le=500),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(DeletedRestaurant).order_by(DeletedRestaurant.deleted_at.desc()).limit(limit)
    if q:
        term = q.strip()
        like = f"%{term.lower()}%"
        condition = (
            func.lower(DeletedRestaurant.restaurant_public_id).like(like)
            | func.lower(DeletedRestaurant.name).like(like)
            | func.lower(func.coalesce(DeletedRestaurant.reason, "")).like(like)
            | func.lower(func.coalesce(DeletedRestaurant.deleted_by, "")).like(like)
        )
        if term.isdigit():
            as_int = int(term)
            condition = condition | (DeletedRestaurant.id == as_int) | (
                DeletedRestaurant.original_restaurant_id == as_int
            )
        stmt = stmt.where(condition)

    rows = session.exec(stmt).all()
    return [
        DeletedRestaurantOut(
            id=row.id,
            restaurant_public_id=row.restaurant_public_id,
            name=row.name,
            deleted_at=row.deleted_at,
            reason=row.reason,
            deleted_by=row.deleted_by,
            extra=json.loads(row.extra_json or "{}"),
        )
        for row in rows
    ]


@router.delete("/restaurants/deleted/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_archived_restaurant(
    entry_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    entry = session.get(DeletedRestaurant, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Archived restaurant not found")
    log_event(
        session,
        actor_type="admin",
        actor_id=None,
        event="restaurant_delete_archive_purge",
        details={"deleted_restaurant_id": entry_id, "restaurant_public_id": entry.restaurant_public_id},
    )
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/gdpr/requests", response_model=List[GdprRequestOut])
def admin_list_gdpr_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(GdprRequest).order_by(GdprRequest.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(GdprRequest.status == status_filter.strip().lower())
    entries = session.exec(stmt).all()
    return [_gdpr_to_out(entry) for entry in entries]


@router.post("/gdpr/requests", response_model=GdprRequestOut, status_code=status.HTTP_201_CREATED)
def admin_create_gdpr_request(
    payload: GdprRequestCreate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    now = now_iso()
    requester_type = _normalize_requester_type(payload.requester_type)
    request_type = _normalize_request_type(payload.request_type)
    entry = GdprRequest(
        requester_type=requester_type,
        requester_id=payload.requester_id,
        requester_email=payload.requester_email.strip() if payload.requester_email else None,
        request_type=request_type,
        status="open",
        details=payload.details,
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    log_event(
        session,
        actor_type="admin",
        actor_id=None,
        event="gdpr_request_created",
        details={
            "gdpr_request_id": entry.id,
            "requester_type": requester_type,
            "request_type": request_type,
        },
    )
    session.commit()
    return _gdpr_to_out(entry)


@router.patch("/gdpr/requests/{request_id}", response_model=GdprRequestOut)
def admin_update_gdpr_request(
    request_id: int,
    payload: GdprRequestUpdate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    entry = session.get(GdprRequest, request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="GDPR request not found")

    changed = False
    if payload.status:
        status_value = payload.status.strip().lower()
        if status_value not in {"open", "in_progress", "completed", "rejected"}:
            raise HTTPException(status_code=400, detail="Invalid status value")
        if status_value != entry.status:
            entry.status = status_value
            changed = True
            if status_value in {"completed", "rejected"}:
                entry.processed_at = entry.processed_at or now_iso()
    if payload.processed_by is not None:
        entry.processed_by = payload.processed_by.strip() or None
        changed = True
    if payload.resolution_notes is not None:
        entry.resolution_notes = payload.resolution_notes
        changed = True

    if changed:
        entry.updated_at = now_iso()
        session.add(entry)
        session.commit()
        log_event(
            session,
            actor_type="admin",
            actor_id=None,
            event="gdpr_request_updated",
            details={
                "gdpr_request_id": entry.id,
                "status": entry.status,
                "processed_by": entry.processed_by,
            },
        )
        session.commit()
        session.refresh(entry)

    return _gdpr_to_out(entry)


@router.post("/restaurants/{rid}/impersonate", response_model=Token)
def admin_impersonate_restaurant(
    rid: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if session.get(Restaurant, rid) is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    log_event(session, actor_type="admin", actor_id=None, event="restaurant_impersonate", details={"restaurant_id": rid})
    session.commit()
    return Token(access_token=create_access_token(f"restaurant:{rid}"))


# ---------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------


YEAR_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


@router.get("/invoices/orders", response_model=List[InvoiceOrderSummary])
def admin_invoice_orders(
    month: Optional[str] = Query(default=None, description="Filter orders by YYYY-MM"),
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = (
        select(Order, Restaurant)
        .join(Restaurant, Order.restaurant_id == Restaurant.id, isouter=True)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if month:
        if not YEAR_MONTH_PATTERN.match(month):
            raise HTTPException(status_code=400, detail="Month must be in YYYY-MM format")
        stmt = stmt.where(Order.created_at.like(f"{month}%"))
    rows = session.exec(stmt).all()
    return [_make_invoice_summary(order, restaurant) for order, restaurant in rows]


@router.get("/invoices/orders/{order_id}/receipt", response_model=InvoiceReceiptOut)
def admin_invoice_order_receipt(
    order_id: int,
    format: Optional[str] = Query(default="json"),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    session.refresh(order, attribute_names=["items", "restaurant"])
    receipt = _make_invoice_receipt(order)
    fmt = (format or "json").lower()
    if fmt == "csv":
        filename = f"receipt_{receipt.order_public_id or receipt.order_id}.csv"
        csv_content = _receipt_to_csv(receipt)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if fmt == "pdf":
        filename = f"receipt_{receipt.order_public_id or receipt.order_id}.pdf"
        pdf_bytes = _receipt_to_pdf(receipt)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return receipt


@router.get("/invoices/monthly", response_model=List[InvoiceMonthSummary])
def admin_invoice_monthly_summary(
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    orders = session.exec(select(Order)).all()
    summary_map: Dict[str, Dict[str, int]] = {}
    for order in orders:
        created = order.created_at or ""
        month = created[:7]
        if not month:
            continue
        bucket = summary_map.setdefault(
            month,
            {
                "order_count": 0,
                "total_cents": 0,
                "shipping_cents": 0,
                "voucher_cents": 0,
                "fee_platform_cents": 0,
                "payout_rest_cents": 0,
            },
        )
        bucket["order_count"] += 1
        bucket["total_cents"] += order.total_cents or 0
        bucket["shipping_cents"] += order.shipping_cents or 0
        bucket["voucher_cents"] += order.voucher_amount_cents or 0
        bucket["fee_platform_cents"] += order.fee_platform_cents or 0
        bucket["payout_rest_cents"] += order.payout_rest_cents or 0

    summaries = [
        InvoiceMonthSummary(
            month=month,
            order_count=data["order_count"],
            total_cents=data["total_cents"],
            shipping_cents=data["shipping_cents"],
            voucher_cents=data["voucher_cents"],
            fee_platform_cents=data["fee_platform_cents"],
            payout_rest_cents=data["payout_rest_cents"],
        )
        for month, data in sorted(summary_map.items(), key=lambda kv: kv[0], reverse=True)
    ]
    return summaries[:24]


@router.get("/invoices/monthly/{year_month}", response_model=List[InvoiceOrderSummary])
def admin_invoice_month_detail(
    year_month: str,
    format: Optional[str] = Query(default="json"),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if not YEAR_MONTH_PATTERN.match(year_month):
        raise HTTPException(status_code=400, detail="Month must be in YYYY-MM format")
    stmt = (
        select(Order, Restaurant)
        .join(Restaurant, Order.restaurant_id == Restaurant.id, isouter=True)
        .where(Order.created_at.like(f"{year_month}%"))
        .order_by(Order.created_at.desc())
    )
    rows = session.exec(stmt).all()
    summaries: List[InvoiceOrderSummary] = []
    shipping_total = voucher_total = fee_total = payout_total = total_gross = 0
    for order, restaurant in rows:
        summaries.append(_make_invoice_summary(order, restaurant))
        shipping_total += order.shipping_cents or 0
        voucher_total += order.voucher_amount_cents or 0
        fee_total += order.fee_platform_cents or 0
        payout_total += order.payout_rest_cents or 0
        total_gross += order.total_cents or 0
    totals = InvoiceMonthSummary(
        month=year_month,
        order_count=len(summaries),
        total_cents=total_gross,
        shipping_cents=shipping_total,
        voucher_cents=voucher_total,
        fee_platform_cents=fee_total,
        payout_rest_cents=payout_total,
    )
    fmt = (format or "json").lower()
    if fmt == "csv":
        filename = f"invoices_{year_month}.csv"
        csv_content = _monthly_summary_to_csv(year_month, summaries, totals)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if fmt == "pdf":
        filename = f"invoices_{year_month}.pdf"
        pdf_bytes = _monthly_summary_to_pdf(year_month, summaries, totals)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return summaries


# ---------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------

# Local DTOs for vouchers
class VoucherCreate(SQLModel):
    code: Optional[str] = None
    currency: Optional[str] = "EUR"
    initial_balance_cents: int
    label: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None


class VoucherUpdate(SQLModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None


class VoucherRedemptionOut(SQLModel):
    order_id: int
    order_public_id: Optional[str] = None
    amount_cents: int
    redeemed_at: str


class VoucherOut(SQLModel):
    id: int
    code: str
    label: Optional[str] = None
    currency: str
    initial_balance_cents: int
    balance_cents: int
    spent_cents: int
    is_active: bool
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    max_redemptions: Optional[int] = None
    created_at: datetime
    redemptions: List[VoucherRedemptionOut] = []


def _generate_voucher_code(n: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def _voucher_to_out(session: Session, voucher: Voucher) -> VoucherOut:
    rows = session.exec(
        select(VoucherRedemption, Order.public_id)
        .join(Order, Order.id == VoucherRedemption.order_id, isouter=True)
        .where(VoucherRedemption.voucher_id == voucher.id)
        .order_by(VoucherRedemption.redeemed_at.desc())
    ).all()
    redemptions = [
        VoucherRedemptionOut(
            order_id=red.order_id,
            order_public_id=order_public_id,
            amount_cents=red.amount_cents,
            redeemed_at=red.redeemed_at,
        )
        for red, order_public_id in rows
    ]
    spent = max(voucher.initial_balance_cents - voucher.balance_cents, 0)
    return VoucherOut(
        id=voucher.id,
        code=voucher.code,
        label=voucher.label,
        currency=voucher.currency,
        initial_balance_cents=voucher.initial_balance_cents,
        balance_cents=voucher.balance_cents,
        spent_cents=spent,
        is_active=bool(voucher.is_active),
        valid_from=voucher.valid_from,
        valid_until=voucher.valid_until,
        max_redemptions=voucher.max_redemptions,
        created_at=voucher.created_at,
        redemptions=redemptions,
    )


@router.post("/vouchers", response_model=VoucherOut, status_code=status.HTTP_201_CREATED)
def admin_create_voucher(
    body: VoucherCreate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    code = (body.code or _generate_voucher_code()).strip().upper()

    # ensure uniqueness (case-insensitive)
    exists = session.exec(
        select(Voucher).where(func.lower(Voucher.code) == code.lower())
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Voucher code already exists")

    currency = (body.currency or "EUR").strip().upper()

    label = body.label.strip() if body.label else None
    v = Voucher(
        code=code,
        currency=currency,
        initial_balance_cents=int(body.initial_balance_cents),
        balance_cents=int(body.initial_balance_cents),
        label=label,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        max_redemptions=body.max_redemptions,
    )
    session.add(v)
    session.commit()
    session.refresh(v)

    log_event(session, actor_type="admin", actor_id=None, event="voucher_create", details={"voucher_id": v.id})
    session.commit()

    return _voucher_to_out(session, v)


@router.get("/vouchers", response_model=List[VoucherOut])
def admin_list_vouchers(
    q: Optional[str] = Query(default=None, description="Search by code (contains, case-insensitive)"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(Voucher).order_by(Voucher.created_at.desc())
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Voucher.code).like(like) | func.lower(func.coalesce(Voucher.label, "")).like(like)
        )

    rows = (
        session.exec(stmt.offset(offset).limit(limit)).unique().all()
    )
    return [_voucher_to_out(session, v) for v in rows]


@router.get("/vouchers/{voucher_id}", response_model=VoucherOut)
def admin_get_voucher(
    voucher_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    v = session.get(Voucher, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return _voucher_to_out(session, v)


@router.patch("/vouchers/{voucher_id}", response_model=VoucherOut)
def admin_update_voucher(
    voucher_id: int,
    body: VoucherUpdate,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    v = session.get(Voucher, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")

    data = body.dict(exclude_unset=True)
    if not data:
        return _voucher_to_out(session, v)

    if "label" in data:
        v.label = data["label"]
    if "is_active" in data and data["is_active"] is not None:
        v.is_active = bool(data["is_active"])
    if "valid_from" in data:
        v.valid_from = data["valid_from"]
    if "valid_until" in data:
        v.valid_until = data["valid_until"]
    if "max_redemptions" in data:
        v.max_redemptions = data["max_redemptions"]

    session.add(v)
    session.commit()
    session.refresh(v)
    log_event(session, actor_type="admin", actor_id=None, event="voucher_update", details={"voucher_id": v.id, **data})
    session.commit()
    return _voucher_to_out(session, v)


@router.delete("/vouchers/{voucher_id}")
def admin_delete_voucher(
    voucher_id: int,
    force: Optional[bool] = False,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    v = session.get(Voucher, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # prevent deletion if redemptions or attached orders exist unless force
    has_redemptions = session.exec(
        select(VoucherRedemption.id).where(VoucherRedemption.voucher_id == voucher_id)
    ).first() is not None
    has_orders = session.exec(
        select(Order.id).where(Order.voucher_id == voucher_id)
    ).first() is not None

    if (has_redemptions or has_orders) and not force:
        raise HTTPException(
            status_code=409,
            detail="Voucher has related orders/redemptions. Use force=true to delete anyway.",
        )

    if has_redemptions:
        session.exec(delete(VoucherRedemption).where(VoucherRedemption.voucher_id == voucher_id))
    if has_orders:
        # if you prefer to preserve orders but just detach voucher:
        session.exec(
            select(Order).where(Order.voucher_id == voucher_id)
        )
        # Set voucher_id = NULL for related orders (safer than deleting orders)
        session.exec(
            Order.__table__.update().where(Order.voucher_id == voucher_id).values(voucher_id=None)
        )

    session.delete(v)
    session.commit()

    log_event(session, actor_type="admin", actor_id=None, event="voucher_delete", details={"voucher_id": voucher_id})
    session.commit()

    return {"ok": True}
