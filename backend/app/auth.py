import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, Worker


def new_token() -> tuple[str, str]:
    t = secrets.token_urlsafe(32)
    return t, hash_token(t)


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()  # high-entropy tokens: fast hash is fine


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    return hash_token(authorization[7:])


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    u = db.scalar(select(User).where(User.api_key_hash == _bearer(authorization)))
    if not u:
        raise HTTPException(401, "invalid api key")
    return u


def current_worker(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Worker:
    w = db.scalar(select(Worker).where(Worker.token_hash == _bearer(authorization)))
    if not w or w.revoked_at:
        raise HTTPException(401, "invalid or revoked worker token")
    return w
