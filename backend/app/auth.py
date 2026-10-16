import hashlib
import logging
import secrets

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import oidc
from .database import get_db
from .models import Account, User, Worker


def new_token() -> tuple[str, str]:
    t = secrets.token_urlsafe(32)
    return t, hash_token(t)


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()  # high-entropy tokens: fast hash is fine


def _raw_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:]


def _bearer(authorization: str | None) -> str:
    return hash_token(_raw_bearer(authorization))


def create_user(db: Session, username: str, **oidc_ids) -> tuple[User, str]:
    """User plus its two accounts, flushed not committed. Returns the API key (shown once)."""
    token, h = new_token()
    u = User(username=username, api_key_hash=h, **oidc_ids)
    db.add(u)
    db.flush()  # IntegrityError on a taken username or OIDC identity
    db.add_all([Account(owner_user_id=u.id, type="user_available"), Account(owner_user_id=u.id, type="user_held")])
    return u, token


def _oidc_user(db: Session, id_token: str) -> User:
    try:
        claims = oidc.verify(id_token)
    except (jwt.PyJWTError, OSError) as e:  # bad token, or issuer unreachable: either way not authenticated
        logging.getLogger(__name__).info("id token rejected: %s", type(e).__name__)  # never log the token itself
        raise HTTPException(401, "invalid id token")
    ids = {"oidc_issuer": claims["iss"], "oidc_subject": claims["sub"]}
    find = select(User).where(User.oidc_issuer == ids["oidc_issuer"], User.oidc_subject == ids["oidc_subject"])
    u = db.scalar(find)
    if u:
        return u
    # First login provisions the user. The API key is discarded: OIDC users authenticate with ID tokens.
    name = "oidc-" + hashlib.sha256(f"{claims['iss']}|{claims['sub']}".encode()).hexdigest()[:16]
    try:
        u, _ = create_user(db, name, **ids)
        db.commit()
    except IntegrityError:  # a concurrent first login won the insert
        db.rollback()
        u = db.scalar(find)
    return u


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    """Bearer is an API key or, when OIDC_ISSUER is set, an OIDC ID token (a JWT; API keys never contain dots)."""
    raw = _raw_bearer(authorization)
    if raw.count(".") == 2 and oidc.issuer():
        return _oidc_user(db, raw)
    u = db.scalar(select(User).where(User.api_key_hash == hash_token(raw)))
    if not u:
        raise HTTPException(401, "invalid api key")
    return u


def current_worker(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Worker:
    w = db.scalar(select(Worker).where(Worker.token_hash == _bearer(authorization)))
    if not w or w.revoked_at:
        raise HTTPException(401, "invalid or revoked worker token")
    return w
