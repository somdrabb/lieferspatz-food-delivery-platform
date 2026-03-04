# backend/routers_restaurants.py
from __future__ import annotations

from typing import Optional, List
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, delete
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .database import get_session
from .models import (
    Restaurant,
    MenuItem,
    OpeningHour,
    DeliveryZip,
    RestaurantUpdate as RestaurantUpdateModel,
)
from .deps import get_current_subject
from .schemas import (
    RestaurantOut,
    RestaurantDetailOut,
    OpeningHourOut,
    OpeningHourCreate,
    DeliveryZipOut,
    DeliveryZipCreate,
    MenuItemOut,
    MenuItemCreate,
    MenuItemUpdate,
)
from .utils import is_restaurant_open

router = APIRouter(prefix="/api/restaurants", tags=["restaurants"])


# ---------------------------
# Helpers
# ---------------------------

def require_restaurant_owner(sub=Depends(get_current_subject)) -> int:
    kind, sid = sub
    if kind != "restaurant":
        raise HTTPException(status_code=403, detail="Restaurant login required")
    return sid


def _parse_now(now: Optional[str]) -> datetime:
    """Parse ISO 'now' or default to current UTC. Accepts 'Z' or naive as UTC."""
    if now:
        try:
            s = now.strip()
            if s.endswith("Z"):
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
            dt = datetime.fromisoformat(s)
            # treat naive as UTC (frontend sends local-naive sometimes)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(400, detail="Invalid 'now' format. Use ISO (e.g. 2025-09-07T12:34:56Z)")
    return datetime.now(timezone.utc)


def _is_open_at(session: Session, r: Restaurant, when_utc: datetime) -> bool:
    return is_restaurant_open(session, r.id, when=when_utc)


def _parse_busy_until(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _to_iso_utc_str(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return val


# ---------------------------
# Public listing & details
# ---------------------------

@router.get("", response_model=List[RestaurantOut], summary="List Restaurants")
def list_restaurants(
    plz: Optional[str] = Query(default=None, description="Customer PLZ to match delivery_zips"),
    now: Optional[str] = Query(default=None, description="ISO datetime (UTC or with Z); used for 'open now' filtering"),
    nearby: bool = Query(default=False, description="If true and PLZ is set, include non-exact PLZ and rank by distance"),
    all_: bool = Query(default=False, alias="all", description="If true, return all restaurants (no open/online filtering)"),
    # optional server-side filters
    free_delivery: bool = Query(default=False, description="Only free delivery"),
    min_order_max: Optional[int] = Query(default=None, description="Max minimum-order (in cents)"),
    halal: bool = Query(default=False, description="Require any halal item in menu"),
    category: Optional[str] = Query(default=None, description="Match menu 'category' (in item.extra)"),
    tag: Optional[str] = Query(default=None, description="Match menu 'tags' (in item.extra)"),
    radius_km: Optional[int] = Query(default=None, alias="radius_km", ge=1, le=100, description="Approximate radius (km) for nearby search"),
    session: Session = Depends(get_session),
):
    """
    Returns restaurants. Typical use:
      - `?plz=10115&nearby=true&now=...` for end-user search
      - `?all=true` for the home rail

    When `all=true`, returns all restaurants ordered by name (no open/online/busy filters).
    Otherwise, filters by:
      - is_online = true
      - not busy (busy_until <= now)
      - open at 'now' (opening_hours)
      - optional: free_delivery, min_order_max, halal/category/tag
      - if `plz` is provided, restrict to those that deliver to that PLZ, unless `nearby=true`
        (then rank exact deliverers first and others by numeric PLZ distance).
    """
    # quick path for `all=true`
    if all_:
        q = select(Restaurant).order_by(Restaurant.name)
        rows = session.exec(q).all()
        return rows

    now_requested = now is not None
    when = _parse_now(now)

    # base: by plz or all
    if plz:
        base_q = select(Restaurant).where(
            Restaurant.id.in_(
                select(DeliveryZip.restaurant_id).where(DeliveryZip.postal_code == plz)
            )
        )
        candidates = session.exec(base_q).all()
        # nearby -> consider all as candidates for later ranking
        if nearby:
            all_rs = session.exec(select(Restaurant)).all()
            by_id = {r.id: r for r in [*candidates, *all_rs]}
            candidates = list(by_id.values())
    else:
        candidates = session.exec(select(Restaurant)).all()

    # online/busy/open filters
    filtered: List[Restaurant] = []
    for r in candidates:
        # is_online
        if not (r.is_online is None or r.is_online is True):
            continue
        # busy
        busy_dt = _parse_busy_until(r.busy_until)
        if busy_dt and busy_dt > when:
            continue
        # apply explicit "open now" filter only when requested
        if now_requested and not _is_open_at(session, r, when):
            continue
        # free delivery
        if free_delivery and (r.delivery_fee_cents or 0) != 0:
            continue
        # min-order ceiling
        if min_order_max is not None and (r.min_order_cents or 0) > int(min_order_max):
            continue
        filtered.append(r)

    # menu-based filters
    if halal or (category or tag):
        out: List[Restaurant] = []
        needles = []
        if category and category.strip():
            needles.append(category.strip().lower())
        if tag and tag.strip():
            needles.append(tag.strip().lower())

        for r in filtered:
            items = session.exec(select(MenuItem).where(MenuItem.restaurant_id == r.id)).all()
            ok = True
            if halal:
                ok = any('"is_halal": true' in (mi.extra_json or "") for mi in items)
            if ok and needles:
                def item_matches(mi: MenuItem) -> bool:
                    ej = (mi.extra_json or "").lower()
                    return any(n in ej for n in needles)
                ok = any(item_matches(mi) for mi in items)
            if ok:
                out.append(r)
        filtered = out

    # optional radius clamp
    radius_limit = None
    plz_int = None
    if plz and radius_km is not None:
        try:
            plz_int = int(plz)
            radius_limit = max(int(radius_km), 0)
        except Exception:
            radius_limit = None

    if plz_int is not None and radius_limit is not None:
        def within_radius(r: Restaurant) -> bool:
            zips = r.zips or []
            diffs = []
            for dz in zips:
                try:
                    diffs.append(abs(int(dz.postal_code) - plz_int))
                except Exception:
                    continue
            if diffs:
                return min(diffs) <= radius_limit
            try:
                return abs(int((r.postal_code or "0")) - plz_int) <= radius_limit
            except Exception:
                return False

        radius_matches = [r for r in filtered if within_radius(r)]
        if radius_matches:
            filtered = radius_matches

    # no ranking needed if no plz/nearby
    if not (plz and nearby):
        return filtered

    # nearby ranking
    if plz_int is None:
        try:
            plz_int = int(plz)
        except (TypeError, ValueError):
            return filtered

    def rank_key(r: Restaurant):
        zips = r.zips or []
        delivers_exact = any(dz.postal_code == plz for dz in zips)
        if delivers_exact:
            return (0, 0)
        diffs = []
        for dz in zips:
            try:
                diffs.append(abs(int(dz.postal_code) - plz_int))
            except Exception:
                continue
        return (1, min(diffs) if diffs else 999_999)

    return sorted(filtered, key=rank_key)


@router.get("/{rid}", response_model=RestaurantDetailOut, summary="Restaurant + menu + hours + zips")
def restaurant_detail(rid: int, session: Session = Depends(get_session)):
    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(404, detail="Not found")
    return {
        "restaurant": r,
        "menu": r.menu_items,         # relationship
        "opening_hours": r.opening_hours,
        "delivery_zips": r.zips,
    }


# ---------------------------
# Menu CRUD (restaurant-owned)
# ---------------------------

@router.get("/{restaurant_id}/menu-items", response_model=List[MenuItemOut])
def list_menu_items(restaurant_id: int, session: Session = Depends(get_session)):
    if session.get(Restaurant, restaurant_id) is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return session.exec(select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)).all()


@router.post("/{rid}/menu-items", response_model=MenuItemOut)
def create_menu_item(
    rid: int,
    body: MenuItemCreate,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    mi = MenuItem(
        restaurant_id=rid,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        price_cents=body.price_cents,
        image_url=body.image_url or None,
    )
    if body.extra is not None:
        mi.extra_json = json.dumps(body.extra or {})
    session.add(mi)
    session.commit()
    session.refresh(mi)
    return mi


@router.patch("/{rid}/menu-items/{mid}", response_model=MenuItemOut)
def update_menu_item(
    rid: int,
    mid: int,
    body: MenuItemUpdate,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")

    mi = session.get(MenuItem, mid)
    if not mi or mi.restaurant_id != rid:
        raise HTTPException(404, "Not found")

    for k, v in body.dict(exclude_unset=True).items():
        if k == "extra":
            mi.extra_json = json.dumps(v or {})
            continue
        if isinstance(v, str):
            v = v.strip()
        setattr(mi, k, v)
    session.add(mi)
    session.commit()
    session.refresh(mi)
    return mi


@router.delete("/{rid}/menu-items/{mid}")
def delete_menu_item(
    rid: int,
    mid: int,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    mi = session.get(MenuItem, mid)
    if not mi or mi.restaurant_id != rid:
        raise HTTPException(404, "Not found")
    session.delete(mi)
    session.commit()
    return {"ok": True}


# ---------------------------
# Restaurant delete
# ---------------------------

@router.delete("/{rid}")
def delete_restaurant(
    rid: int,
    session: Session = Depends(get_session),
    my_rid: int = Depends(require_restaurant_owner),
):
    if rid != my_rid:
        raise HTTPException(403, "You can only delete your own restaurant")

    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(404, "Restaurant not found")

    try:
        session.exec(delete(MenuItem).where(MenuItem.restaurant_id == rid))
        session.exec(delete(OpeningHour).where(OpeningHour.restaurant_id == rid))
        session.exec(delete(DeliveryZip).where(DeliveryZip.restaurant_id == rid))
        session.commit()
        session.delete(r)
        session.commit()
        return {"ok": True}
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(409, "Cannot delete: existing references (e.g., orders).") from e


# ---------------------------
# Opening Hours CRUD
# ---------------------------

@router.get("/{rid}/opening-hours", response_model=List[OpeningHourOut])
def list_opening_hours(
    rid: int,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    return session.exec(
        select(OpeningHour).where(OpeningHour.restaurant_id == rid)
    ).all()


@router.post("/{rid}/opening-hours", response_model=OpeningHourOut)
def add_opening_hour(
    rid: int,
    body: OpeningHourCreate,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")

    weekday = body.weekday
    if weekday < 0 or weekday > 6:
        raise HTTPException(400, "Weekday must be between 0 (Mon) and 6 (Sun)")

    def _canonical_time(value: str) -> str:
        if not value or not value.strip():
            raise HTTPException(400, "Opening hours require HH:MM values")
        try:
            return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
        except ValueError as exc:
            raise HTTPException(400, "Time must be in HH:MM format") from exc

    open_time = _canonical_time(body.open_time)
    close_time = _canonical_time(body.close_time)
    if close_time <= open_time:
        raise HTTPException(400, "Close time must be after open time")

    exists = session.exec(
        select(OpeningHour).where(
            OpeningHour.restaurant_id == rid,
            OpeningHour.weekday == weekday,
            OpeningHour.open_time == open_time,
            OpeningHour.close_time == close_time,
        )
    ).first()
    if exists:
        return exists

    oh = OpeningHour(
        restaurant_id=rid,
        weekday=weekday,
        open_time=open_time,
        close_time=close_time,
    )
    session.add(oh)
    session.commit()
    session.refresh(oh)
    return oh


@router.delete("/{rid}/opening-hours/{ohid}")
def delete_opening_hour(
    rid: int,
    ohid: int,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    oh = session.get(OpeningHour, ohid)
    if not oh or oh.restaurant_id != rid:
        raise HTTPException(404, "Not found")
    session.delete(oh)
    session.commit()
    return {"ok": True}


# ---------------------------
# Delivery ZIPs CRUD
# ---------------------------

@router.get("/{rid}/delivery-zips", response_model=List[DeliveryZipOut])
def list_delivery_zips(
    rid: int,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    return session.exec(
        select(DeliveryZip).where(DeliveryZip.restaurant_id == rid)
    ).all()


@router.post("/{rid}/delivery-zips", response_model=DeliveryZipOut)
def add_delivery_zip(
    rid: int,
    body: DeliveryZipCreate,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")

    postal_code = (body.postal_code or "").strip()
    if not postal_code:
        raise HTTPException(400, "Postal code is required")
    if len(postal_code) < 4 or len(postal_code) > 10:
        raise HTTPException(400, "Postal code looks invalid")

    exists = session.exec(
        select(DeliveryZip).where(
            DeliveryZip.restaurant_id == rid,
            DeliveryZip.postal_code == postal_code,
        )
    ).first()
    if exists:
        return exists

    dz = DeliveryZip(restaurant_id=rid, postal_code=postal_code)
    session.add(dz)
    session.commit()
    session.refresh(dz)
    return dz


@router.delete("/{rid}/delivery-zips/{dzid}")
def delete_delivery_zip(
    rid: int,
    dzid: int,
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    if kind != "restaurant" or sid != rid:
        raise HTTPException(403, "Forbidden")
    dz = session.get(DeliveryZip, dzid)
    if not dz or dz.restaurant_id != rid:
        raise HTTPException(404, "Not found")
    session.delete(dz)
    session.commit()
    return {"ok": True}


# ---------------------------
# Restaurant profile update
# ---------------------------

@router.patch("/{rid}")
def update_restaurant(
    rid: int,
    payload: RestaurantUpdateModel,
    session: Session = Depends(get_session),
    owner_rid: int = Depends(require_restaurant_owner),
):
    if owner_rid != rid:
        raise HTTPException(403, "You can only edit your own restaurant")

    r = session.get(Restaurant, rid)
    if not r:
        raise HTTPException(404, "Restaurant not found")

    # unique rename
    if payload.name and payload.name != r.name:
        exists = session.exec(
            select(Restaurant).where(Restaurant.name == payload.name, Restaurant.id != rid)
        ).first()
        if exists:
            raise HTTPException(400, "Restaurant name already taken")
        r.name = payload.name

    # email change (ensure uniqueness, stored lower-case)
    if payload.email is not None and payload.email != (r.email or ""):
        email_norm = payload.email.strip().lower()
        if email_norm:
            exists_email = session.exec(
                select(Restaurant).where(
                    func.lower(Restaurant.email) == email_norm,
                    Restaurant.id != rid,
                )
            ).first()
            if exists_email:
                raise HTTPException(400, "Email already in use")
            r.email = email_norm

    # simple fields
    for attr in [
        "street", "city", "postal_code", "description", "image_url",
        "min_order_cents", "delivery_fee_cents", "prep_time_min", "is_online",
    ]:
        if getattr(payload, attr) is not None:
            setattr(r, attr, getattr(payload, attr))

    # busy_until
    if payload.busy_until is not None:
        r.busy_until = _to_iso_utc_str(payload.busy_until)

    # merge extra
    if payload.extra is not None:
        base = r.extra or {}
        base.update({k: v for k, v in payload.extra.items() if v is not None})
        r.extra = base

    session.add(r)
    session.commit()
    session.refresh(r)
    return r
