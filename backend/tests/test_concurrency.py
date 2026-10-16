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



def _settle_counts(jid):
    from app.models import LedgerPosting, LedgerTransaction
    with SessionLocal() as db:
        kinds = [k for (k,) in db.execute(select(LedgerTransaction.kind).where(LedgerTransaction.ref_job_id == jid))]
        total = db.scalar(select(func.sum(LedgerPosting.amount)))
    return kinds, total


def test_concurrent_duplicate_results_settle_exactly_once():
    """A worker's retry storm: the same result posted 6 times at once. One settles; the rest are no-op 200s."""
    for i in range(5):  # several rounds widen the chance of a true overlap
        _duplicate_round(i)


def _duplicate_round(i):
    cons, contrib = user(1000), user()
    w = worker(contrib)
    jid = TestClient(app).post("/jobs", json={"model": "m", "prompt": f"p{i}", "max_tokens": 50}, headers=cons).json()["id"]
    TestClient(app).post(f"/workers/{w[0]}/lease", json={"models": ["m"]}, headers=w[1])
    res = {"output": "o", "prompt_tokens": 1, "completion_tokens": 20}
    clients = [TestClient(app) for _ in range(6)]  # one client per thread
    out = race(*[lambda c=c: c.post(f"/jobs/{jid}/result", json=res, headers=w[1]) for c in clients])
    assert [r.status_code for r in out] == [200] * 6
    assert sorted(r.json()["settled"] for r in out) == [False] * 5 + [True]
    kinds, total = _settle_counts(jid)
    assert kinds.count("settle") == 1 and total == 0
    # A second settle would push held to -50 and pay 40: held 0 means no overdraw.
    assert bal(contrib) == {"available": 20, "held": 0} and bal(cons) == {"available": 980, "held": 0}


def test_concurrent_ledger_settles_with_one_key_post_once():
    """Backstop below the API's compare-and-set: 6 sessions post the same job's settle at once. The unique
    idempotency key lets exactly one through, so the held reservation is drained once and never overdrawn."""
    from sqlalchemy.exc import IntegrityError
    cons, contrib = user(1000), user()
    jid = TestClient(app).post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 50}, headers=cons).json()["id"]
    with SessionLocal() as db:
        j = db.get(Job, jid)
        held = user_account(db, j.consumer_user_id, "user_held").id
        back = user_account(db, j.consumer_user_id, "user_available").id
        earner = user_account(db, TestClient(app).get("/users/me", headers=contrib).json()["id"], "user_available").id

    def settle():
        with SessionLocal() as db:
            try:
                tx = post(db, "settle", f"job:{jid}:settle", [(held, -50), (earner, 20), (back, 30)], jid)
                db.commit()
                return "posted" if tx else "replay"
            except IntegrityError:  # the unique key refused a racing duplicate; its whole tx rolls back
                db.rollback()
                return "refused"
    out = race(*[settle] * 6)
    assert out.count("posted") == 1, out
    kinds, total = _settle_counts(jid)
    assert kinds.count("settle") == 1 and total == 0
    assert bal(contrib) == {"available": 20, "held": 0} and bal(cons) == {"available": 980, "held": 0}


def test_result_racing_lease_expiry_never_both_settles_and_refunds():
    """The sweeper reaps an expired lease while the worker's late result arrives: exactly one of them wins."""
    from datetime import timedelta

    from app.models.ledger import now
    from app.routers.workers import reap_expired
    from sqlalchemy import update

    def one(i):
        cons, contrib = user(1000), user()
        w = worker(contrib)
        jid = TestClient(app).post("/jobs", json={"model": "m", "prompt": f"q{i}", "max_tokens": 50}, headers=cons).json()["id"]
        with SessionLocal() as db:
            db.execute(update(Job).where(Job.id == jid).values(max_attempts=1))
            db.commit()
        TestClient(app).post(f"/workers/{w[0]}/lease", json={"models": ["m"]}, headers=w[1])
        with SessionLocal() as db:
            db.execute(update(Job).where(Job.id == jid).values(lease_expires_at=now() - timedelta(seconds=1)))
            db.commit()

        def reap():
            with SessionLocal() as db:
                reap_expired(db, now())
        ca = TestClient(app)
        race(lambda: ca.post(f"/jobs/{jid}/result", json={"output": "o", "prompt_tokens": 1, "completion_tokens": 20},
                             headers=w[1]), reap)
        kinds, total = _settle_counts(jid)
        assert total == 0 and sorted(set(kinds) - {"reserve"}) in (["settle"], ["refund"]), kinds
        expected = {"available": 980, "held": 0} if "settle" in kinds else {"available": 1000, "held": 0}
        assert bal(cons) == expected
    for i in range(5):
        one(i)
