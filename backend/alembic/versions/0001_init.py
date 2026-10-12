"""initial schema"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None

BigInt = sa.BigInteger().with_variant(sa.Integer, "sqlite")
TS = sa.DateTime(timezone=True)


def pk():
    return sa.Column("id", sa.Integer, primary_key=True)


def fk(name, target, **kw):
    return sa.Column(name, sa.Integer, sa.ForeignKey(target), **kw)


def upgrade():
    op.create_table("users", pk(), sa.Column("username", sa.String, nullable=False, unique=True),
                    sa.Column("api_key_hash", sa.String, nullable=False, unique=True),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("accounts", pk(), fk("owner_user_id", "users.id", index=True),
                    sa.Column("type", sa.String, nullable=False), sa.Column("unit", sa.String, nullable=False))
    op.create_table("workers", pk(), fk("owner_user_id", "users.id", nullable=False),
                    sa.Column("name", sa.String, nullable=False),
                    sa.Column("token_hash", sa.String, nullable=False, unique=True),
                    sa.Column("revoked_at", TS), sa.Column("created_at", TS, nullable=False))
    op.create_table("jobs", pk(), fk("consumer_user_id", "users.id", nullable=False, index=True),
                    sa.Column("model", sa.String, nullable=False), sa.Column("prompt", sa.Text, nullable=False),
                    sa.Column("max_tokens", sa.Integer, nullable=False), sa.Column("reserved", BigInt, nullable=False),
                    sa.Column("status", sa.String, nullable=False, index=True), fk("worker_id", "workers.id"),
                    sa.Column("lease_expires_at", TS), sa.Column("output", sa.Text),
                    sa.Column("created_at", TS, nullable=False))
    op.create_table("job_attempts", pk(), fk("job_id", "jobs.id", nullable=False, index=True),
                    fk("worker_id", "workers.id", nullable=False), sa.Column("leased_at", TS, nullable=False),
                    sa.Column("lease_expires_at", TS, nullable=False))
    op.create_table("ledger_transactions", pk(), sa.Column("kind", sa.String, nullable=False),
                    sa.Column("idempotency_key", sa.String, nullable=False, unique=True),
                    fk("ref_job_id", "jobs.id"), sa.Column("created_at", TS, nullable=False))
    op.create_table("ledger_postings", pk(), fk("tx_id", "ledger_transactions.id", nullable=False, index=True),
                    fk("account_id", "accounts.id", nullable=False, index=True),
                    sa.Column("amount", BigInt, nullable=False), sa.CheckConstraint("amount <> 0"))
    op.create_table("usage_receipts", pk(), fk("job_id", "jobs.id", nullable=False),
                    fk("attempt_id", "job_attempts.id"), fk("worker_id", "workers.id", nullable=False),
                    sa.Column("prompt_tokens", sa.Integer, nullable=False),
                    sa.Column("completion_tokens", sa.Integer, nullable=False),
                    sa.Column("eval_duration_ns", BigInt, nullable=False), sa.Column("charged", BigInt, nullable=False),
                    fk("tx_id", "ledger_transactions.id", nullable=False), sa.Column("created_at", TS, nullable=False),
                    sa.UniqueConstraint("job_id"))


def downgrade():
    for t in ["usage_receipts", "ledger_postings", "ledger_transactions", "job_attempts", "jobs", "workers", "accounts", "users"]:
        op.drop_table(t)
