from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def now():
    return datetime.now(UTC)


# BigInteger on Postgres; SQLite needs Integer for autoincrement PKs.
BigInt = BigInteger().with_variant(Integer, "sqlite")
TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    api_key_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Account(Base):
    """type: user_available | user_held | issuance | platform_reserve. Owner NULL for system accounts."""
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="TEST_CREDIT")  # test-only credits, no cash value


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    disputes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Job(Base):
    """status: queued | leased | completed | failed (max attempts, refunded) | disputed (redundancy mismatch, refunded)"""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consumer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(Text)
    max_tokens: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(BigInt)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TS)
    output: Mapped[str | None] = mapped_column(Text)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    temperature: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    redundant: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    leased_at: Mapped[datetime] = mapped_column(TS, default=now)
    lease_expires_at: Mapped[datetime] = mapped_column(TS)
    # Worker-reported result, kept per attempt so redundant runs can be compared.
    output: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    eval_duration_ns: Mapped[int | None] = mapped_column(BigInt)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class LedgerTransaction(Base):
    """Append-only; no status column. idempotency_key makes every posting group happen once."""
    __tablename__ = "ledger_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    ref_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class LedgerPosting(Base):
    __tablename__ = "ledger_postings"
    __table_args__ = (CheckConstraint("amount <> 0"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tx_id: Mapped[int] = mapped_column(ForeignKey("ledger_transactions.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInt)  # integer minor units, signed


class UsageReceipt(Base):
    """Worker-reported usage. NOT verified: see judge.md blocker 2."""
    __tablename__ = "usage_receipts"
    __table_args__ = (UniqueConstraint("job_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("job_attempts.id"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    eval_duration_ns: Mapped[int] = mapped_column(BigInt, default=0)
    charged: Mapped[int] = mapped_column(BigInt)
    tx_id: Mapped[int] = mapped_column(ForeignKey("ledger_transactions.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
