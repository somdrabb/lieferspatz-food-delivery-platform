from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from .models import (Customer, Restaurant, MenuItem, Order, OrderItem,
                     WalletAccount, WalletTxn, RestaurantNotification)
from .models import DeliveryZip
from .schemas import OrderDetailOut, OrderOut, OrderItemSnapshotOut, CustomerSlimOut, OrderCreate
from .utils import round_split, now_iso, log_event, is_restaurant_open, generate_public_id
from .ws import manager
from datetime import datetime
from typing import Optional, List
from sqlalchemy import case, desc
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from .database import get_session
from .deps import get_current_subject


router = APIRouter(prefix="/api/orders", tags=["orders"])


# ---------- helpers ----------

def is_open_now(session: Session, rid: int, dt: Optional[datetime] = None) -> bool:
    if dt is not None:
        return is_restaurant_open(session, rid, when=dt)
    return is_restaurant_open(session, rid)

def delivers_to(session: Session, rid: int, plz: str) -> bool:
    return session.exec(
        select(DeliveryZip).where(
            DeliveryZip.restaurant_id == rid,
            DeliveryZip.postal_code == plz,
        )
    ).first() is not None

def _order_sort_clause():
    # running first (in_bearbeitung, in_zubereitung), then others; newest first
    running = ["in_bearbeitung", "in_zubereitung", "paused_by_restaurant", "paused_by_admin"]
    return (
        case((Order.status.in_(running), 0), else_=1),
        desc(Order.created_at),
    )
def get_wallet(session: Session, kind: str, ref_id: int):
    return session.exec(select(WalletAccount).where(WalletAccount.account_type==kind, WalletAccount.ref_id==ref_id)).first()

def get_platform_wallet(session: Session):
    return session.exec(select(WalletAccount).where(WalletAccount.account_type=="platform")).first()



@router.post("")
def submit_order(
    body: OrderCreate,
    background_tasks: BackgroundTasks,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(403, "Customer token required")

    cust = session.get(Customer, sid)
    if not cust:
        raise HTTPException(404, "Customer not found")

    rest = session.get(Restaurant, body.restaurant_id)
    if not rest:
        raise HTTPException(404, "Restaurant not found")

    postal = (cust.postal_code or "").strip()
    if postal and not delivers_to(session, rest.id, postal):
        raise HTTPException(400, "Restaurant does not deliver to your postal code")
    if not is_open_now(session, rest.id):
        raise HTTPException(400, "Restaurant is closed right now")

    items = []
    subtotal = 0
    for it in body.items:
        mi = session.get(MenuItem, it.menu_item_id)
        if not mi or mi.restaurant_id != rest.id: raise HTTPException(400, "Invalid menu item")
        subtotal += mi.price_cents * it.quantity
        items.append((mi, it.quantity))

    fee, payout = round_split(subtotal)
    total = subtotal

    w_c = get_wallet(session, "customer", cust.id)
    if not w_c: raise HTTPException(400, "Customer wallet missing")
    if w_c.balance_cents < total: raise HTTPException(400, "Insufficient funds")

    w_r = get_wallet(session, "restaurant", rest.id)
    if not w_r:
        w_r = WalletAccount(account_type="restaurant", ref_id=rest.id, balance_cents=0)
        session.add(w_r)
        session.flush()

    w_p = get_platform_wallet(session)
    if not w_p:
        w_p = WalletAccount(account_type="platform", ref_id=None, balance_cents=0)
        session.add(w_p)
        session.flush()

    order = Order(
        customer_id=cust.id,
        restaurant_id=rest.id,
        status="in_bearbeitung",
        payment_status="paid",
        payment_method="wallet",
        note_for_kitchen=body.note_for_kitchen or "",
        subtotal_cents=subtotal,
        shipping_cents=0,
        fee_platform_cents=fee,
        payout_rest_cents=payout,
        voucher_amount_cents=0,
        total_cents=total,
        public_id=generate_public_id(session, Order, "public_id", prefix="ORD"),
    )
    session.add(order); session.flush()
    for mi, qty in items:
        session.add(OrderItem(order_id=order.id, menu_item_id=mi.id, name_snapshot=mi.name,
                              price_cents_snapshot=mi.price_cents, quantity=qty))

    session.add(WalletTxn(account_id=w_c.id, amount_cents=-total, reason="order_charge", order_id=order.id)); w_c.balance_cents -= total
    session.add(WalletTxn(account_id=w_r.id, amount_cents=+payout, reason="order_payout_restaurant", order_id=order.id)); w_r.balance_cents += payout
    session.add(WalletTxn(account_id=w_p.id, amount_cents=+fee, reason="order_fee_platform", order_id=order.id)); w_p.balance_cents += fee

    session.add(RestaurantNotification(restaurant_id=rest.id, order_id=order.id, type="new_order"))
    session.commit(); session.refresh(order)
    # audit
    log_event(session, actor_type="customer", actor_id=cust.id, event="order_created",
              details={"order_id": order.id, "restaurant_id": rest.id, "total_cents": total})
    session.commit()
    background_tasks.add_task(manager.broadcast, rest.id, {"type":"new_order","order_id":order.id,"created_at":order.created_at,"total_cents":order.total_cents})
    return {
        "order_id": order.id,
        "order_public_id": order.public_id,
        "status": order.status,
        "total_cents": order.total_cents,
    }

def list_orders_for(kind: str, sid: int, session: Session):
    q = select(Order)
    if kind == "customer":
        q = q.where(
            Order.customer_id == sid,
            Order.hidden_for_customer == False,
        )
    else:
        q = q.where(
            Order.restaurant_id == sid,
            Order.hidden_for_restaurant == False,
        )
    q = q.order_by(*_order_sort_clause())
    q = q.options(
        selectinload(Order.items),
        selectinload(Order.restaurant),
        selectinload(Order.voucher),
    )
    return session.exec(q).all()


@router.get("", response_model=List[OrderOut])
def my_orders(sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind not in ("customer", "restaurant"):
        raise HTTPException(403, "Forbidden")
    return list_orders_for(kind, sid, session)

@router.post("/{oid}/confirm")
def confirm_order(oid: int, background_tasks: BackgroundTasks, sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind != "restaurant": raise HTTPException(403, "Restaurant token required")
    order = session.get(Order, oid)
    if not order or order.restaurant_id != sid: raise HTTPException(404, "Order not found")
    previous_status = order.status
    if previous_status not in ("in_bearbeitung", "paused_by_restaurant"): raise HTTPException(400, "Invalid state")
    now = now_iso()
    if previous_status == "in_bearbeitung":
        order.confirmed_at = now
    order.status = "in_zubereitung"
    order.updated_at = now
    session.add(RestaurantNotification(restaurant_id=sid, order_id=order.id, type="status_change"))
    session.commit()
    # audit
    log_event(session, actor_type="restaurant", actor_id=sid, event="order_confirmed",
              details={"order_id": order.id, "previous_status": previous_status, "new_status": order.status})
    session.commit()
    background_tasks.add_task(manager.broadcast, sid, {"type":"status_change","order_id":order.id,"status":order.status,"at":order.updated_at})
    return {"ok": True}

@router.post("/{oid}/pause")
def pause_order(oid: int, background_tasks: BackgroundTasks, sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind != "restaurant": raise HTTPException(403, "Restaurant token required")
    order = session.get(Order, oid)
    if not order or order.restaurant_id != sid: raise HTTPException(404, "Order not found")
    previous_status = order.status
    if previous_status not in ("in_bearbeitung", "in_zubereitung"): raise HTTPException(400, "Invalid state")
    now = now_iso()
    order.status = "paused_by_restaurant"
    order.updated_at = now
    session.add(RestaurantNotification(restaurant_id=sid, order_id=order.id, type="status_change"))
    session.commit()
    log_event(session, actor_type="restaurant", actor_id=sid, event="order_paused",
              details={"order_id": order.id, "previous_status": previous_status, "new_status": order.status})
    session.commit()
    background_tasks.add_task(manager.broadcast, sid, {"type":"status_change","order_id":order.id,"status":order.status,"at":order.updated_at})
    return {"ok": True}

@router.post("/{oid}/complete")
def complete_order(oid: int, background_tasks: BackgroundTasks, sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind != "restaurant": raise HTTPException(403, "Restaurant token required")
    order = session.get(Order, oid)
    if not order or order.restaurant_id != sid: raise HTTPException(404, "Order not found")
    if order.status not in ("in_zubereitung",): raise HTTPException(400, "Invalid state")
    now = now_iso()
    order.status = "abgeschlossen"; order.closed_at = now; order.updated_at = now
    session.add(RestaurantNotification(restaurant_id=sid, order_id=order.id, type="status_change"))
    session.commit()
    log_event(session, actor_type="restaurant", actor_id=sid, event="order_completed",
              details={"order_id": order.id})
    session.commit()
    background_tasks.add_task(manager.broadcast, sid, {"type":"status_change","order_id":order.id,"status":order.status,"at":order.closed_at})
    return {"ok": True}

@router.post("/{oid}/reject")
def reject_order(oid: int, background_tasks: BackgroundTasks, sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    kind, sid = sub
    if kind != "restaurant": raise HTTPException(403, "Restaurant token required")
    order = session.get(Order, oid)
    if not order or order.restaurant_id != sid: raise HTTPException(404, "Order not found")
    if order.status not in ("in_bearbeitung","in_zubereitung","paused_by_restaurant","paused_by_admin"): raise HTTPException(400, "Invalid state")

    w_c = session.exec(select(WalletAccount).where(WalletAccount.account_type=="customer", WalletAccount.ref_id==order.customer_id)).first()
    w_r = session.exec(select(WalletAccount).where(WalletAccount.account_type=="restaurant", WalletAccount.ref_id==order.restaurant_id)).first()
    w_p = session.exec(select(WalletAccount).where(WalletAccount.account_type=="platform")).first()

    from .models import WalletTxn
    session.add(WalletTxn(account_id=w_c.id, amount_cents=+order.total_cents, reason="refund", order_id=order.id)); w_c.balance_cents += order.total_cents
    session.add(WalletTxn(account_id=w_r.id, amount_cents=-order.payout_rest_cents, reason="reverse_payout", order_id=order.id)); w_r.balance_cents -= order.payout_rest_cents
    session.add(WalletTxn(account_id=w_p.id, amount_cents=-order.fee_platform_cents, reason="reverse_fee", order_id=order.id)); w_p.balance_cents -= order.fee_platform_cents

    now = now_iso()
    order.status = "storniert"; order.closed_at = now; order.updated_at = now
    session.add(RestaurantNotification(restaurant_id=sid, order_id=order.id, type="status_change"))
    session.commit()
    log_event(session, actor_type="restaurant", actor_id=sid, event="order_rejected",
              details={"order_id": order.id})
    session.commit()
    background_tasks.add_task(manager.broadcast, sid, {"type":"status_change","order_id":order.id,"status":order.status,"at":order.closed_at})
    return {"ok": True}

@router.get("/{oid}", response_model=OrderDetailOut)
def order_detail(oid: int, sub=Depends(get_current_subject), session: Session = Depends(get_session)):
    """
    Order detail with immutable item snapshots + customer basics.
    Access: the order's customer OR the order's restaurant.
    """
    order = session.get(Order, oid)
    if not order:
        raise HTTPException(404, "Not found")

    kind, sid = sub
    if not (
        (kind == "customer" and order.customer_id == sid)
        or (kind == "restaurant" and order.restaurant_id == sid)
    ):
        raise HTTPException(403, "Forbidden")

    items = session.exec(select(OrderItem).where(OrderItem.order_id == oid)).all()
    cust = session.get(Customer, order.customer_id)

    return OrderDetailOut(
        order=OrderOut.from_orm(order),
        items=[OrderItemSnapshotOut.from_orm(i) for i in items],
        customer=CustomerSlimOut(
            id=cust.id,
            first_name=cust.first_name,
            last_name=cust.last_name,
            street=cust.street,
            postal_code=cust.postal_code,
            city=cust.city,
            phone=cust.phone,
        ),
    )
