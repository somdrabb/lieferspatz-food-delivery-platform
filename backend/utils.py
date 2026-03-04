from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, Iterable
import json
import secrets
import string

from sqlmodel import Session, select
from .models import AuditLog, OpeningHour

def round_split(subtotal_cents: int) -> Tuple[int, int]:
    fee = round(subtotal_cents * 0.15)
    payout = subtotal_cents - fee
    return int(fee), int(payout)

def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(session: Session, *, actor_type: str, actor_id: Optional[int], event: str, details: Optional[Dict[str, Any]] = None, ip: Optional[str] = None) -> None:
    """Persist a structured audit log entry. Best-effort; do not raise on failure."""
    try:
        entry = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            event=event,
            details_json=json.dumps(details or {}),
            ip=ip,
        )
        session.add(entry)
    except Exception:
        # do not break main flow if logging fails
        pass


MINUTES_PER_DAY = 24 * 60


def _parse_hhmm_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        hour_str, minute_str = value.strip().split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if hour == 24 and minute == 0:
            return MINUTES_PER_DAY
        if not (0 <= hour < 24) or not (0 <= minute < 60):
            return None
        return hour * 60 + minute
    except Exception:
        return None


def opening_slot_matches(
    slot_weekday: int,
    open_time: str,
    close_time: str,
    target_weekday: int,
    target_minute: int,
) -> bool:
    start = _parse_hhmm_to_minutes(open_time)
    end = _parse_hhmm_to_minutes(close_time)
    if start is None or end is None:
        return False

    # Exact 24h (open == close)
    if start == end:
        return slot_weekday == target_weekday

    # Same-day window
    if start < end:
        if slot_weekday != target_weekday:
            return False
        return start <= target_minute < min(end, MINUTES_PER_DAY)

    # Overnight window (crosses midnight)
    if slot_weekday == target_weekday and target_minute >= start:
        return True
    next_weekday = (slot_weekday + 1) % 7
    if next_weekday == target_weekday and target_minute < min(end, MINUTES_PER_DAY):
        return True
    return False


def opening_hours_contains(opening_hours: Iterable[OpeningHour], when: datetime) -> bool:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    weekday = when.weekday()
    minute = when.hour * 60 + when.minute
    for oh in opening_hours:
        if opening_slot_matches(oh.weekday, oh.open_time, oh.close_time, weekday, minute):
            return True
    return False


def is_restaurant_open(session: Session, restaurant_id: int, *, when: Optional[datetime] = None) -> bool:
    when = when or datetime.now(timezone.utc)
    openings = session.exec(
        select(OpeningHour).where(OpeningHour.restaurant_id == restaurant_id)
    ).all()
    return opening_hours_contains(openings, when)


def generate_public_id(
    session: Session,
    model: Any,
    field_name: str,
    *,
    prefix: str,
    length: int = 6,
) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(length))
        candidate = f"{prefix}-{datetime.utcnow():%y%m%d}-{suffix}"
        exists = session.exec(
            select(model).where(getattr(model, field_name) == candidate)
        ).first()
        if not exists:
            return candidate
