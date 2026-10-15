"""Races the lease and the reservation. The threaded tests run on any DB; the row-lock and SKIP LOCKED ones need Postgres
(run with TEST_DATABASE_URL, see AGENTS.md)."""
import threading

import pytest
from app.database import SessionLocal
from app.ledger import InsufficientFunds, post, spend, system_account
from app.main import app
from app.models import Job, JobAttempt
from app.routers.users import user_account
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_hardening import bal, user, worker


def race(*calls):
    """Run each call in its own thread, released together by a barrier; returns their results in order."""
    gate, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, f):
        gate.wait()
        out[i] = f()
    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def test_two_workers_one_job_exactly_one_lease():
    cons = user(1000)
    a, b = worker(user()), worker(user())
    jid = TestClient(app).post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 10}, headers=cons).json()["id"]
    ca, cb = TestClient(app), TestClient(app)  # one client per thread
    codes = race(lambda: ca.post(f"/workers/{a[0]}/lease", json={"models": ["m"]}, headers=a[1]).status_code,
                 lambda: cb.post(f"/workers/{b[0]}/lease", json={"models": ["m"]}, headers=b[1]).status_code)
    assert sorted(codes) == [200, 204]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == jid)) == 1


def test_concurrent_reservations_cannot_overdraw():
    cons = user(1000)
    ca, cb = TestClient(app), TestClient(app)
    body = {"model": "m", "prompt": "p", "max_tokens": 600}
    codes = race(lambda: ca.post("/jobs", json=body, headers=cons).status_code,
                 lambda: cb.post("/jobs", json=body, headers=cons).status_code)
    assert sorted(codes) == [201, 402]
    assert bal(cons) == {"available": 400, "held": 600}


def needs_postgres():
    with SessionLocal() as probe:
        if probe.bind.dialect.name != "postgresql":
            pytest.skip("row locks need Postgres (set TEST_DATABASE_URL)")


def test_second_spender_waits_for_the_first_and_sees_its_debit():
    """Deterministic version of the overdraw race: the account row lock in ledger.spend serializes spenders."""
    needs_postgres()
    uid = TestClient(app).post("/users", json={"username": "spender"}).json()["id"]
    with SessionLocal() as db:
        avail, held = user_account(db, uid, "user_available").id, user_account(db, uid, "user_held").id
        post(db, "fund", "fund:spender", [(system_account(db, "issuance").id, -1000), (avail, 1000)])
        db.commit()
    first, result = SessionLocal(), []
    spend(first, avail, held, 600, "reserve", "a")  # holds the row lock until commit

    def second():
        with SessionLocal() as db:
            try:
                spend(db, avail, held, 600, "reserve", "b")
                db.commit()
                result.append("spent")
            except InsufficientFunds:
                result.append("refused")
    t = threading.Thread(target=second)
    t.start()
    t.join(0.5)
    blocked = t.is_alive()
    first.commit()  # always release, or a failure here would hang the next test's schema drop
    first.close()
    t.join(5)
    assert blocked, "second spender must block on the lock, not read the stale balance"
    assert result == ["refused"]


def test_skip_locked_hides_a_job_another_worker_is_claiming():
    needs_postgres()
    cons = user(1000)
    b = worker(user())
    TestClient(app).post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 10}, headers=cons)
    with SessionLocal() as holder:  # worker A is mid-claim: row locked, transaction open
        assert holder.scalar(select(Job.id).where(Job.status == "queued").with_for_update(skip_locked=True)) is not None
        assert TestClient(app).post(f"/workers/{b[0]}/lease", json={"models": ["m"]}, headers=b[1]).status_code == 204
        holder.rollback()
    assert TestClient(app).post(f"/workers/{b[0]}/lease", json={"models": ["m"]}, headers=b[1]).status_code == 200

