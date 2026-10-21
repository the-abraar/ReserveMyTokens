import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import oidc
from ..auth import create_user, current_user
from ..database import get_db
from ..ledger import balance, post, system_account
from ..models import Account, User
from ..ratelimit import limit

router = APIRouter()


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class Fund(BaseModel):
    user_id: int
    amount: int = Field(gt=0)


def user_account(db: Session, user_id: int, type_: str) -> Account:
    return db.scalar(select(Account).where(Account.owner_user_id == user_id, Account.type == type_))


@router.post("/users", status_code=201, dependencies=[Depends(limit("signup", per_ip=True))])
def register(body: NewUser, db: Session = Depends(get_db)):
    """Auth: none, deliberately: API-key signup. Closed (403) once a real OIDC issuer is configured outside dev."""
    if os.getenv("OIDC_ISSUER") and not oidc.is_dev():
        raise HTTPException(403, "sign up through OIDC login")
    try:
        u, token = create_user(db, body.username)
    except IntegrityError:
        raise HTTPException(409, "username taken")
    db.commit()
    return {"id": u.id, "api_key": token}  # shown once


@router.get("/users/me")
def me(u: User = Depends(current_user)):
    return {"id": u.id, "username": u.username, "oidc": u.oidc_subject is not None}


@router.get("/users/me/balance")
def my_balance(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"available": balance(db, user_account(db, u.id, "user_available").id),
            "held": balance(db, user_account(db, u.id, "user_held").id)}


def require_admin(x_admin_token: str = Header("")):
    """Auth: ADMIN_TOKEN from the environment; admin routes are off (403) when it is unset."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(403, "forbidden")
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):  # bytes: non-ASCII must not raise
        raise HTTPException(401, "bad admin token")


@router.post("/admin/fund", dependencies=[Depends(require_admin)])
def fund(body: Fund, idempotency_key: str = Header(""), db: Session = Depends(get_db)):
    """Test-only credit issuance."""
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key header required")
    acc = user_account(db, body.user_id, "user_available")
    if not acc:
        raise HTTPException(404, "no such user")
    post(db, "fund", f"fund:{idempotency_key}", [(system_account(db, "issuance").id, -body.amount), (acc.id, body.amount)])
    db.commit()
    return {"ok": True}
