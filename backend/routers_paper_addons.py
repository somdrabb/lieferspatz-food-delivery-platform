from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .database import get_session
from .deps import get_current_subject
from .models import Customer, Restaurant, DeliveryZip, Order
from .schemas import RestaurantOut
from .utils import is_restaurant_open

router = APIRouter(prefix="/api", tags=["paper-compliance"])

# ---------- A) "Open now & delivers to my PLZ" (customer convenience) ----------
@router.get("/restaurants/nearby-open", response_model=List[RestaurantOut])
def nearby_open_restaurants(
    session: Session = Depends(get_session),
    sub = Depends(get_current_subject)
):
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(403, "Nur Kunden dürfen diese Liste abrufen")
    cust = session.get(Customer, sid)
    if not cust:
        raise HTTPException(404, "Kunde nicht gefunden")

    # Filter restaurants that deliver to customer's PLZ
    q = select(Restaurant).where(
        Restaurant.id.in_(
            select(DeliveryZip.restaurant_id).where(DeliveryZip.postal_code == cust.postal_code)
        )
    )
    rows = session.exec(q).all()

    # Keep only those open at server "now"
    now = datetime.now(timezone.utc)

    open_now = []
    for r in rows:
        if is_restaurant_open(session, r.id, when=now):
            open_now.append(r)

    return open_now


# ---------- B) Customer order history with mandated sort ----------
@router.get("/customers/me/orders")
def my_orders(
    session: Session = Depends(get_session),
    sub = Depends(get_current_subject)
):
    kind, sid = sub
    if kind != "customer":
        raise HTTPException(403, "Nur Kunden dürfen diese Liste abrufen")

    # Running first (not abgeschlossen/storniert), newest first within each group
    running = session.exec(
        select(Order)
        .where(
            Order.customer_id == sid,
            Order.hidden_for_customer == False,
            Order.status.not_in(["abgeschlossen", "storniert"]),
        )
        .order_by(Order.created_at.desc())
    ).all()
    done = session.exec(
        select(Order)
        .where(
            Order.customer_id == sid,
            Order.hidden_for_customer == False,
            Order.status.in_(["abgeschlossen", "storniert"]),
        )
        .order_by(Order.created_at.desc())
    ).all()

    return running + done


# ---------- C) Restaurant order list with mandated sort (alt route) ----------
# (You already have GET /api/orders for restaurants; this adds an explicit version
#  under the restaurant scope that guarantees the sort order the paper asks for.)
@router.get("/restaurants/{rid}/orders")
def restaurant_orders(
    rid: int,
    session: Session = Depends(get_session),
    sub = Depends(get_current_subject)
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Nur das Restaurant selbst darf seine Bestellungen sehen")

    running = session.exec(
        select(Order)
        .where(
            Order.restaurant_id == rid,
            Order.hidden_for_restaurant == False,
            Order.status.not_in(["abgeschlossen", "storniert"]),
        )
        .order_by(Order.created_at.desc())
    ).all()
    done = session.exec(
        select(Order)
        .where(
            Order.restaurant_id == rid,
            Order.hidden_for_restaurant == False,
            Order.status.in_(["abgeschlossen", "storniert"]),
        )
        .order_by(Order.created_at.desc())
    ).all()

    return running + done
