import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/import.db"  # placeholder; fixture swaps per test
os.environ["ADMIN_TOKEN"] = "test-admin"
# Tests sign up many users from one client; test_hardening lowers these to test the limits themselves.
os.environ["RATE_SIGNUP_PER_MIN"] = os.environ["RATE_PROJECT_PER_MIN"] = "1000"

import pytest
from alembic import command
from alembic.config import Config
from app import database
from sqlalchemy import create_engine, text

ROOT = os.path.join(os.path.dirname(__file__), "..")
# Set to a THROWAWAY Postgres database (its public schema is dropped before every test) to run the suite there.
PG_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Every test gets an empty DB migrated with `alembic upgrade head` (env.py reads database.engine):
    a new SQLite file by default, or a wiped public schema on TEST_DATABASE_URL."""
    eng = create_engine(PG_URL or f"sqlite:///{tmp_path}/t.db")
    if PG_URL:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    database.engine = eng
    database.SessionLocal.configure(bind=eng)
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield
    eng.dispose()
