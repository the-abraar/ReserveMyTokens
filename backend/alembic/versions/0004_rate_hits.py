"""shared fixed-window rate-limit counters (one row per bucket and token)"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.create_table("rate_hits", sa.Column("bucket", sa.String, primary_key=True),
                    sa.Column("key_hash", sa.String, primary_key=True),
                    sa.Column("minute", sa.Integer, nullable=False), sa.Column("hits", sa.Integer, nullable=False))


def downgrade():
    op.drop_table("rate_hits")
