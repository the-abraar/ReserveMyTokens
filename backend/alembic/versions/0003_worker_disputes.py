"""per-worker dispute counter"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column("workers", sa.Column("disputes", sa.Integer, nullable=False, server_default="0"))


def downgrade():
    op.drop_column("workers", "disputes")
