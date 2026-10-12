"""max attempts, redundancy, per-attempt results"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
BigInt = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade():
    op.add_column("jobs", sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"))
    op.add_column("jobs", sa.Column("temperature", sa.Float, nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("redundant", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("job_attempts", sa.Column("output", sa.Text))
    op.add_column("job_attempts", sa.Column("prompt_tokens", sa.Integer))
    op.add_column("job_attempts", sa.Column("completion_tokens", sa.Integer))
    op.add_column("job_attempts", sa.Column("eval_duration_ns", BigInt))
    op.add_column("job_attempts", sa.Column("flagged", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    for c in ("flagged", "eval_duration_ns", "completion_tokens", "prompt_tokens", "output"):
        op.drop_column("job_attempts", c)
    for c in ("redundant", "temperature", "max_attempts"):
        op.drop_column("jobs", c)
