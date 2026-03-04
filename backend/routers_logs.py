from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from sqlmodel import Session, select

from .database import get_session
from .deps import get_current_subject
from .models import AuditLog

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/me")
def my_logs(
    limit: int = Query(50, ge=1, le=500),
    sub=Depends(get_current_subject),
    session: Session = Depends(get_session),
):
    kind, sid = sub
    q = (
        select(AuditLog)
        .where(AuditLog.actor_type == kind, AuditLog.actor_id == sid)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    return session.exec(q).all()

