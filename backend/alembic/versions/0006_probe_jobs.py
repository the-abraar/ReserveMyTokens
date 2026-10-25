"""known-answer probe jobs"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.add_column("jobs", sa.Column("expected_output", sa.Text))
    op.add_column("jobs", sa.Column("expected_tokens", sa.Integer))


def downgrade():
    op.drop_column("jobs", "expected_tokens")
    op.drop_column("jobs", "expected_output")
