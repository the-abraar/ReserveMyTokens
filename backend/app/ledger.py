from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, LedgerPosting, LedgerTransaction


class InsufficientFunds(Exception):
    pass


def balance(db: Session, account_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(LedgerPosting.amount), 0)).where(LedgerPosting.account_id == account_id))


def post(db: Session, kind: str, key: str, postings: list[tuple[int, int]], ref_job_id: int | None = None):
    """Insert one balanced transaction. Returns None if `key` was already posted (idempotent no-op)."""
    postings = [(a, amt) for a, amt in postings if amt != 0]
    assert all(isinstance(amt, int) for _, amt in postings), "integer minor units only"
    assert postings and sum(amt for _, amt in postings) == 0, "postings must sum to zero"
    if db.scalar(select(LedgerTransaction.id).where(LedgerTransaction.idempotency_key == key)):
        return None
    tx = LedgerTransaction(kind=kind, idempotency_key=key, ref_job_id=ref_job_id)
    db.add(tx)
    db.flush()  # unique key is the backstop against concurrent duplicate posts
    db.add_all(LedgerPosting(tx_id=tx.id, account_id=a, amount=amt) for a, amt in postings)
    return tx


def spend(db: Session, src: int, dst: int, amount: int, kind: str, key: str, ref_job_id=None):
    """Move `amount` src->dst, refusing to overdraw src. Row lock serializes spenders on Postgres
    (SQLite serializes writers anyway)."""
    db.execute(select(Account.id).where(Account.id == src).with_for_update()).one()
    if balance(db, src) < amount:
        raise InsufficientFunds
    return post(db, kind, key, [(src, -amount), (dst, amount)], ref_job_id)


def system_account(db: Session, type_: str) -> Account:
    acc = db.scalar(select(Account).where(Account.type == type_, Account.owner_user_id.is_(None)))
    if not acc:
        acc = Account(type=type_)
        db.add(acc)
        db.flush()
    return acc
