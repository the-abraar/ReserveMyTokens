"""OIDC identity, worker signing key and presence, signed attempts, job idempotency key, project registry"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
TS = sa.DateTime(timezone=True)


def upgrade():
    op.add_column("users", sa.Column("oidc_issuer", sa.String))
    op.add_column("users", sa.Column("oidc_subject", sa.String))
    op.create_index("ux_users_oidc", "users", ["oidc_issuer", "oidc_subject"], unique=True)
    op.add_column("workers", sa.Column("public_key", sa.String))
    op.add_column("workers", sa.Column("last_seen_at", TS))
    op.add_column("workers", sa.Column("models", sa.String))
    op.add_column("job_attempts", sa.Column("signature", sa.String))
    op.add_column("jobs", sa.Column("idempotency_key", sa.String))
    op.create_index("ux_jobs_consumer_idem", "jobs", ["consumer_user_id", "idempotency_key"], unique=True)
    op.create_table("projects", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("name", sa.String, nullable=False, unique=True), sa.Column("url", sa.String, nullable=False),
                    sa.Column("description", sa.Text, nullable=False),
                    sa.Column("maintainer_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=False, unique=True),
                    sa.Column("verified_at", TS), sa.Column("created_at", TS, nullable=False))


def downgrade():
    op.drop_table("projects")
    op.drop_index("ux_jobs_consumer_idem", "jobs")
    with op.batch_alter_table("jobs") as b:
        b.drop_column("idempotency_key")
    with op.batch_alter_table("job_attempts") as b:
        b.drop_column("signature")
    with op.batch_alter_table("workers") as b:
        for c in ("models", "last_seen_at", "public_key"):
            b.drop_column(c)
    op.drop_index("ux_users_oidc", "users")
    with op.batch_alter_table("users") as b:
        b.drop_column("oidc_subject")
        b.drop_column("oidc_issuer")
