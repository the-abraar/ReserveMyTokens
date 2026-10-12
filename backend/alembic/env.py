from alembic import context
from app import models  # noqa: F401
from app.database import Base, engine

with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
