import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, SQLModel, Field

from .database import get_session
from .deps import require_admin
from .models import Order, OrderEvent, RestaurantNotification, Restaurant, DeletedOrder
from .schemas import OrderSummaryOut, OrderSummaryItem
from .routers_admin import ADMIN_PASSWORD
from .utils import now_iso, log_event

router = APIRouter(prefix="/api/admin/orders", tags=["admin-orders"])


class OrderDeletePayload(SQLModel):
    reason: Optional[str] = None
    deleted_by: Optional[str] = None


class OrderPurgePayload(OrderDeletePayload):
    password: str


class DeletedOrderOut(SQLModel):
    order_id: Optional[int] = None
    order_public_id: Optional[str] = None
    restaurant_public_id: Optional[str] = None
    restaurant_name: Optional[str] = None
    deleted_at: str
    deleted_by: Optional[str] = None
    reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


def _order_to_summary(order: Order) -> OrderSummaryOut:
    items = [
        OrderSummaryItem(
            id=item.id,
            name=item.name_snapshot,
            quantity=item.quantity,
            price_cents=item.price_cents_snapshot,
        )
        for item in order.items
    ]
    return OrderSummaryOut(
        id=order.id,
        public_id=order.public_id,
        restaurant_id=order.restaurant_id,
        restaurant_public_id=order.restaurant.public_id if order.restaurant else None,
        customer_id=order.customer_id,
        status=order.status,
        payment_status=order.payment_status,
        subtotal_cents=order.subtotal_cents,
        shipping_cents=order.shipping_cents,
        voucher_amount_cents=order.voucher_amount_cents,
        total_cents=order.total_cents,
        created_at=order.created_at,
        voucher_code=order.voucher.code if order.voucher else None,
        items=items,
    )


def _deleted_order_to_out(entry: DeletedOrder) -> DeletedOrderOut:
    try:
        details = json.loads(entry.details_json or "{}")
    except Exception:
        details = {}
    restaurant_name = details.get("restaurant_name")
    return DeletedOrderOut(
        order_id=entry.order_id,
        order_public_id=entry.order_public_id,
        restaurant_public_id=entry.restaurant_public_id,
        restaurant_name=restaurant_name,
        deleted_at=entry.deleted_at,
        deleted_by=entry.deleted_by,
        reason=entry.reason,
        details=details,
    )


def _upsert_deleted_order(
    session: Session,
    order: Order,
    *,
    previous_status: str,
    action: str,
    reason: Optional[str],
    deleted_by: Optional[str],
) -> None:
    session.refresh(order, attribute_names=["restaurant"])
    payload = {
        "action": action,
        "status_before": previous_status,
        "status_after": order.status,
        "total_cents": order.total_cents,
        "shipping_cents": order.shipping_cents,
        "voucher_amount_cents": order.voucher_amount_cents,
        "created_at": order.created_at,
        "restaurant_name": order.restaurant.name if order.restaurant else None,
    }
    existing = session.exec(select(DeletedOrder).where(DeletedOrder.order_id == order.id)).first()
    now = now_iso()
    if existing:
        existing.reason = reason or existing.reason
        existing.deleted_by = deleted_by or existing.deleted_by
        existing.deleted_at = now
        existing.restaurant_id = order.restaurant_id
        existing.restaurant_public_id = order.restaurant.public_id if order.restaurant else None
        existing.customer_id = order.customer_id
        existing.details_json = json.dumps(payload)
        session.add(existing)
    else:
        session.add(
            DeletedOrder(
                order_id=order.id,
                order_public_id=order.public_id,
                restaurant_id=order.restaurant_id,
                restaurant_public_id=order.restaurant.public_id if order.restaurant else None,
                customer_id=order.customer_id,
                deleted_at=now,
                deleted_by=deleted_by,
                reason=reason,
                details_json=json.dumps(payload),
            )
        )


@router.get("", response_model=List[OrderSummaryOut])
def list_orders(
    q: Optional[str] = Query(default=None, description="Search by order/restaurant public id"),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    base_stmt = select(Order).where(Order.admin_visible == True)

    if q:
        term = q.strip()
        like = f"%{term.lower()}%"
        condition = (
            func.lower(Order.public_id).like(like)
            | func.lower(func.coalesce(Restaurant.public_id, "")).like(like)
            | func.lower(func.coalesce(Restaurant.name, "")).like(like)
        )
        if term.isdigit():
            condition = condition | (Order.id == int(term))
        stmt = base_stmt.join(Restaurant, Order.restaurant_id == Restaurant.id, isouter=True).where(condition)
    else:
        stmt = base_stmt

    stmt = (
        stmt.options(
            selectinload(Order.items),
            selectinload(Order.restaurant),
            selectinload(Order.voucher),
        )
        .order_by(Order.created_at.desc())
        .limit(250)
    )

    rows = session.exec(stmt).unique().all()
    return [_order_to_summary(o) for o in rows]


@router.get("/{order_id}", response_model=OrderSummaryOut)
def get_order(
    order_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    session.refresh(order, attribute_names=["items", "restaurant", "voucher"])
    return _order_to_summary(order)


def _ensure_order(session: Session, order_id: int) -> Order:
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _log_admin_action(session: Session, order: Order, event: str, details: dict) -> None:
    session.add(
        OrderEvent(
            order_id=order.id,
            event=event,
            payload_json=json.dumps(details),
        )
    )
    if order.restaurant_id:
        session.add(
            RestaurantNotification(
                restaurant_id=order.restaurant_id,
                order_id=order.id,
                type="admin_action",
            )
        )
    log_event(
        session,
        actor_type="admin",
        actor_id=None,
        event=event,
        details={"order_id": order.id, **details},
    )


@router.post("/{order_id}/pause", response_model=OrderSummaryOut)
def pause_order(
    order_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    order = _ensure_order(session, order_id)
    previous_status = order.status
    order.status = "paused_by_admin"
    order.updated_at = now_iso()
    _log_admin_action(
        session,
        order,
        event="order_paused_admin",
        details={
            "previous_status": previous_status,
            "new_status": order.status,
        },
    )
    session.commit()
    session.refresh(order)
    return _order_to_summary(order)


@router.post("/{order_id}/complete", response_model=OrderSummaryOut)
def complete_order_admin(
    order_id: int,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    order = _ensure_order(session, order_id)
    previous_status = order.status
    now = now_iso()
    order.status = "abgeschlossen"
    order.updated_at = now
    if not order.closed_at:
        order.closed_at = now
    _log_admin_action(
        session,
        order,
        event="order_completed_admin",
        details={
            "previous_status": previous_status,
            "new_status": order.status,
        },
    )
    session.commit()
    session.refresh(order)
    return _order_to_summary(order)


@router.post("/{order_id}/delete", response_model=OrderSummaryOut)
def delete_order_admin(
    order_id: int,
    payload: Optional[OrderDeletePayload] = Body(default=None),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    order = _ensure_order(session, order_id)
    previous_status = order.status
    now = now_iso()
    order.status = "deleted_by_admin"
    order.updated_at = now
    order.admin_visible = False
    reason = payload.reason.strip() if payload and payload.reason else None
    deleted_by = payload.deleted_by.strip() if payload and payload.deleted_by else None
    _upsert_deleted_order(
        session,
        order,
        previous_status=previous_status,
        action="delete",
        reason=reason,
        deleted_by=deleted_by,
    )
    _log_admin_action(
        session,
        order,
        event="order_deleted_admin",
        details={
            "previous_status": previous_status,
            "new_status": order.status,
            "admin_visible": order.admin_visible,
            "reason": reason,
            "deleted_by": deleted_by,
        },
    )
    session.commit()
    session.refresh(order)
    return _order_to_summary(order)


@router.post("/{order_id}/purge", response_model=OrderSummaryOut)
def purge_order_admin(
    order_id: int,
    payload: OrderPurgePayload = Body(...),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    password = (payload.password or "").strip()
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid admin password")
    order = _ensure_order(session, order_id)
    previous_status = order.status
    now = now_iso()
    order.status = "purged_by_admin"
    order.updated_at = now
    if not order.closed_at:
        order.closed_at = now
    order.admin_visible = False
    order.hidden_for_customer = True
    order.hidden_for_restaurant = True
    reason = payload.reason.strip() if payload.reason else None
    deleted_by = payload.deleted_by.strip() if payload.deleted_by else None
    _upsert_deleted_order(
        session,
        order,
        previous_status=previous_status,
        action="purge",
        reason=reason,
        deleted_by=deleted_by,
    )
    _log_admin_action(
        session,
        order,
        event="order_purged_admin",
        details={
            "previous_status": previous_status,
            "new_status": order.status,
            "hidden_for_customer": order.hidden_for_customer,
            "hidden_for_restaurant": order.hidden_for_restaurant,
            "reason": reason,
            "deleted_by": deleted_by,
        },
    )
    session.commit()
    session.refresh(order)
    return _order_to_summary(order)


@router.get("/deleted", response_model=List[DeletedOrderOut])
def list_deleted_orders(
    q: Optional[str] = Query(default=None, description="Filter by order id, public id, restaurant id or admin"),
    limit: int = Query(default=200, ge=1, le=500),
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(DeletedOrder).order_by(DeletedOrder.deleted_at.desc()).limit(limit)
    if q:
        term = q.strip()
        like = f"%{term.lower()}%"
        condition = (
            func.lower(func.coalesce(DeletedOrder.order_public_id, "")).like(like)
            | func.lower(func.coalesce(DeletedOrder.restaurant_public_id, "")).like(like)
            | func.lower(func.coalesce(DeletedOrder.deleted_by, "")).like(like)
            | func.lower(func.coalesce(DeletedOrder.reason, "")).like(like)
            | func.lower(func.coalesce(DeletedOrder.details_json, "")).like(like)
        )
        if term.isdigit():
            condition = condition | (DeletedOrder.order_id == int(term))
        stmt = stmt.where(condition)

    rows = session.exec(stmt).all()
    return [_deleted_order_to_out(row) for row in rows]
