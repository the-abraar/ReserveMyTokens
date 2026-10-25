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
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def now():
    return datetime.now(UTC)


# BigInteger on Postgres; SQLite needs Integer for autoincrement PKs.
BigInt = BigInteger().with_variant(Integer, "sqlite")


class _UTCDateTime(TypeDecorator):
    """Timezone-aware column that always reads back in UTC: SQLite drops tzinfo, Postgres uses the session zone."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)  # written in UTC


TS = _UTCDateTime()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    api_key_hash: Mapped[str] = mapped_column(String, unique=True)
    oidc_issuer: Mapped[str | None] = mapped_column(String)  # (issuer, subject) unique: migration 0005
    oidc_subject: Mapped[str | None] = mapped_column(String)
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
    public_key: Mapped[str | None] = mapped_column(String)  # base64 Ed25519; signs usage receipts, set once
    last_seen_at: Mapped[datetime | None] = mapped_column(TS)
    models: Mapped[str | None] = mapped_column(String)  # comma-joined, as advertised on the last lease call
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
    idempotency_key: Mapped[str | None] = mapped_column(String)  # unique per consumer: migration 0005
    # Known-answer probe (migration 0006): set => admin-made, never charged or paid, graded on the worker's output and tokens.
    expected_output: Mapped[str | None] = mapped_column(Text)
    expected_tokens: Mapped[int | None] = mapped_column(Integer)
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
    signature: Mapped[str | None] = mapped_column(String)  # worker's Ed25519 signature over app.receipts.payload


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


class Project(Base):
    """Open-source project in the donation registry. Donations go to its own `project_budget` account and are
    irrevocable. verified_at is set by an admin after moderation; only verified projects are listed or funded."""
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    url: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    maintainer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
