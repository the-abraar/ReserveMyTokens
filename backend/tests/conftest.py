import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/import.db"  # placeholder; fixture swaps per test
os.environ["ADMIN_TOKEN"] = "test-admin"

import pytest
from alembic import command
from alembic.config import Config
from app import database, ratelimit
from sqlalchemy import create_engine

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Every test gets its own SQLite file migrated with `alembic upgrade head` (env.py reads database.engine)."""
    eng = create_engine(f"sqlite:///{tmp_path}/t.db")
    database.engine = eng
    database.SessionLocal.configure(bind=eng)
    ratelimit._hits.clear()
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield
    eng.dispose()
