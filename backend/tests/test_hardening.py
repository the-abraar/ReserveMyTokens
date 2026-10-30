from datetime import timedelta

from app import ratelimit
from app.database import SessionLocal
from app.main import app
from app.models import Job, JobAttempt, LedgerPosting, UsageReceipt, Worker
from app.models.ledger import now
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

c = TestClient(app)
n = [0]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def user(funds=0):
    n[0] += 1
    u = c.post("/users", json={"username": f"u{n[0]}"}).json()
    if funds:
        c.post("/admin/fund", json={"user_id": u["id"], "amount": funds}, headers={"X-Admin-Token": "test-admin", "Idempotency-Key": f"seed{n[0]}"})
    return H(u["api_key"])


def worker(h):
    w = c.post("/workers", json={"name": "w"}, headers=h).json()
    return w["id"], H(w["token"])


def lease(w):
    return c.post(f"/workers/{w[0]}/lease", json={"models": ["m"]}, headers=w[1])


def bal(h):
    return c.get("/users/me/balance", headers=h).json()


def submit(jid, w, out, tok=10):
    return c.post(f"/jobs/{jid}/result", headers=w[1], json={"output": out, "prompt_tokens": 1, "completion_tokens": tok}).json()


def expire(jid):
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == jid).values(lease_expires_at=now() - timedelta(seconds=1)))
        db.commit()


def test_lease_expiry_requeues_then_fails_and_refunds():
    cons, contrib = user(1000), user()
    w = worker(contrib)
    jid = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 100}, headers=cons).json()["id"]
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == jid).values(max_attempts=2))
        db.commit()
    for _ in range(2):  # attempt 1 and 2 both expire
        assert lease(w).json()["job_id"] == jid
        expire(jid)
        if _ == 0:
            assert bal(cons) == {"available": 900, "held": 100}  # still reserved after the first expiry
    assert lease(w).status_code == 204  # reaps: attempts == max_attempts -> failed
    assert c.get(f"/jobs/{jid}", headers=cons).json()["status"] == "failed"
    assert bal(cons) == {"available": 1000, "held": 0}
    assert bal(contrib) == {"available": 0, "held": 0}
    assert lease(w).status_code == 204  # refund is not repeated
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0
        assert db.scalar(select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == jid)) == 2


def test_redundancy_agree_pays_disagree_does_not(monkeypatch):
    monkeypatch.setenv("REDUNDANCY_PROB", "1.0")
    cons, a_owner, b_owner = user(1000), user(), user()
    a, b = worker(a_owner), worker(b_owner)
    j1 = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 100}, headers=cons).json()["id"]
    assert lease(a).json()["job_id"] == j1
    assert submit(j1, a, "same", 40)["status"] == "awaiting_verification"
    assert bal(a_owner)["available"] == 0  # nothing paid yet
    assert lease(a).status_code == 204  # same worker may not verify its own result
    assert lease(b).json()["job_id"] == j1
    assert submit(j1, b, "same", 30)["settled"] is True
    assert bal(a_owner)["available"] == 30 and bal(b_owner)["available"] == 0  # min of reported tokens, first worker paid
    assert bal(cons) == {"available": 970, "held": 0}

    j2 = c.post("/jobs", json={"model": "m", "prompt": "p2", "max_tokens": 100}, headers=cons).json()["id"]
    lease(a), submit(j2, a, "x")
    lease(b)
    assert submit(j2, b, "y")["status"] == "disputed"
    assert c.get(f"/jobs/{j2}", headers=cons).json()["status"] == "disputed"
    assert bal(a_owner)["available"] == 30  # no payout
    assert bal(cons) == {"available": 970, "held": 0}  # reservation refunded
    with SessionLocal() as db:
        assert [x.flagged for x in db.scalars(select(JobAttempt).where(JobAttempt.job_id == j2))] == [True, True]
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0


def test_rate_limit(monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "submit", 2)
    monkeypatch.setitem(ratelimit.LIMITS, "lease", 1)
    cons, contrib = user(1000), user()
    codes = [c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 1}, headers=cons).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    other = user(1000)  # limit is per token
    assert c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 1}, headers=other).status_code == 201
    w = worker(contrib)
    assert [lease(w).status_code in (200, 204), lease(w).status_code] == [True, 429]


def test_signup_and_project_submit_are_rate_limited(monkeypatch):
    monkeypatch.setitem(ratelimit.LIMITS, "signup", 2)
    monkeypatch.setitem(ratelimit.LIMITS, "project", 1)
    # Signup is per client IP, so a fresh Authorization header per call does not reset it.
    codes = [c.post("/users", json={"username": f"rl{i}"}, headers=H(f"x{i}")).status_code for i in range(3)]
    assert codes == [201, 201, 429]
    with SessionLocal() as db:
        db.execute(text("UPDATE rate_hits SET minute = minute - 1"))  # next window
        db.commit()
    a, b = user(), user()

    def proj(h, name):
        return c.post("/projects", json={"name": name, "url": "https://example.org", "description": "d"}, headers=h)

    assert [proj(a, "p1").status_code, proj(a, "p2").status_code] == [201, 429]
    assert proj(b, "p3").status_code == 201  # per user token


def test_timestamps_read_back_in_utc():
    """SQLite drops tzinfo on read; every API timestamp must still carry +00:00, like the POST /jobs response."""
    cons, contrib = user(1000), user()
    posted = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 1}, headers=cons).json()
    assert posted["created_at"].endswith("+00:00")
    assert c.get(f"/jobs/{posted['id']}", headers=cons).json()["created_at"] == posted["created_at"]
    assert c.get("/jobs", headers=cons).json()[0]["created_at"] == posted["created_at"]
    w = worker(contrib)
    lease(w)
    [listed] = c.get("/workers", headers=contrib).json()
    assert listed["created_at"].endswith("+00:00") and listed["last_seen_at"].endswith("+00:00")
    with SessionLocal() as db:
        assert db.get(Job, posted["id"]).created_at.utcoffset() == timedelta(0)


def test_rate_limit_is_shared_through_the_database(monkeypatch):
    """The count lives in rate_hits, not process memory, so another API process sees the same hits."""
    monkeypatch.setitem(ratelimit.LIMITS, "submit", 2)
    cons = user(1000)
    for _ in range(2):
        assert c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 1}, headers=cons).status_code == 201
    with SessionLocal() as db:
        assert db.execute(text("SELECT hits FROM rate_hits WHERE bucket = 'submit'")).scalar_one() == 2
        db.execute(text("UPDATE rate_hits SET minute = minute - 1"))  # age the window: next hit starts a new one
        db.commit()
    assert c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 1}, headers=cons).status_code == 201
    with SessionLocal() as db:
        db.execute(text("UPDATE rate_hits SET minute = minute - 1"))
        db.commit()
        ratelimit.prune(db)
        assert db.scalar(text("SELECT count(*) FROM rate_hits")) == 0


def test_verifier_share_paid_with_balanced_postings(monkeypatch):
    monkeypatch.setenv("REDUNDANCY_PROB", "1.0")
    monkeypatch.setenv("REDUNDANCY_VERIFIER_PCT", "25")
    cons, a_owner, b_owner = user(1000), user(), user()
    a, b = worker(a_owner), worker(b_owner)
    j = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 100}, headers=cons).json()["id"]
    lease(a), submit(j, a, "same", 40)
    lease(b)
    assert submit(j, b, "same", 40)["charged"] == 40
    assert (bal(a_owner)["available"], bal(b_owner)["available"]) == (30, 10)  # 40 - 25% / 25%
    assert bal(cons) == {"available": 960, "held": 0}
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0


def test_sweeper_reaps_without_worker_poll(monkeypatch):
    import time

    from app.routers import workers as wr
    monkeypatch.setattr(wr, "LEASE_TTL", timedelta(milliseconds=50))
    monkeypatch.setenv("SWEEP_INTERVAL_SECONDS", "0.05")
    cons, contrib = user(1000), user()
    w = worker(contrib)
    jid = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 100}, headers=cons).json()["id"]
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == jid).values(max_attempts=1))
        db.commit()
    assert lease(w).json()["job_id"] == jid
    with TestClient(app):  # runs lifespan -> sweeper; no further lease calls are made
        for _ in range(60):
            if c.get(f"/jobs/{jid}", headers=cons).json()["status"] == "failed":
                break
            time.sleep(0.05)
    assert c.get(f"/jobs/{jid}", headers=cons).json()["status"] == "failed"
    assert bal(cons) == {"available": 1000, "held": 0}


def test_same_owner_cannot_verify_and_consumer_cannot_verify(monkeypatch):
    monkeypatch.setenv("REDUNDANCY_PROB", "1.0")
    cons, owner = user(1000), user()
    a, a2 = worker(owner), worker(owner)  # two workers, one owner
    j = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 10}, headers=cons).json()["id"]
    lease(a), submit(j, a, "x")
    assert lease(a2).status_code == 204  # same owner, different worker id: refused
    cw = worker(cons)  # the consumer's own worker is refused too
    assert lease(cw).status_code == 204
    assert c.get(f"/jobs/{j}", headers=cons).json()["status"] == "queued"


def test_disputes_suspend_worker(monkeypatch):
    monkeypatch.setenv("REDUNDANCY_PROB", "1.0")
    monkeypatch.setenv("DISPUTE_SUSPEND_AFTER", "2")
    cons, ao, bo = user(1000), user(), user()
    a, b = worker(ao), worker(bo)
    for i in range(2):
        j = c.post("/jobs", json={"model": "m", "prompt": f"p{i}", "max_tokens": 10}, headers=cons).json()["id"]
        lease(a), submit(j, a, "x")
        lease(b)
        assert submit(j, b, "y")["status"] == "disputed"
    assert lease(a).status_code == 401 and lease(b).status_code == 401


def test_admin_fund_idempotency_and_nonascii_token():
    cons = c.post("/users", json={"username": "fx"}).json()
    body = {"user_id": cons["id"], "amount": 50}
    ok = {"X-Admin-Token": "test-admin"}
    assert c.post("/admin/fund", json=body, headers=ok).status_code == 400  # key required
    for _ in range(2):  # retry with the same key funds once
        assert c.post("/admin/fund", json=body, headers={**ok, "Idempotency-Key": "k"}).status_code == 200
    assert bal(H(cons["api_key"]))["available"] == 50
    r = c.post("/admin/fund", json=body, headers={"X-Admin-Token": "t\u00e9st".encode("utf-8"), "Idempotency-Key": "k2"})
    assert r.status_code == 401


def test_probe_pays_like_a_job_when_right_and_strikes_when_wrong(monkeypatch):
    monkeypatch.setenv("DISPUTE_SUSPEND_AFTER", "2")
    adm = {"X-Admin-Token": "test-admin"}
    body = {"model": "m", "prompt": "2+2?", "max_tokens": 8, "expected_output": "4", "expected_tokens": 1}
    assert c.post("/admin/probes", json=body).status_code in (401, 403)  # admin only
    cons, owner = user(100), user()
    w = worker(owner)
    paid = c.post("/jobs", json={"model": "m", "prompt": "2+2?", "max_tokens": 8}, headers=cons).json()["id"]
    assert lease(w).json()["job_id"] == paid
    paid_reply = submit(paid, w, "4", 1)
    ids = [c.post("/admin/probes", json=body, headers=adm).json()["id"] for _ in range(3)]
    replies = []
    for jid, (out, tok) in zip(ids, [("4", 1), ("5", 1), ("4", 9)]):  # pass, wrong output, wrong token count
        assert lease(w).json()["job_id"] == jid
        replies.append(submit(jid, w, out, tok))
    assert replies[0] == paid_reply == {"status": "completed", "settled": True, "charged": 1}  # a probe looks paid
    assert replies[1] == replies[2] == {"status": "completed", "settled": False}
    assert bal(owner) == {"available": 2, "held": 0}  # paid job + passing probe; the wrong ones earn nothing
    with SessionLocal() as db:
        assert [a.flagged for a in db.scalars(select(JobAttempt).order_by(JobAttempt.id))] == [False, False, True, True]
        x = db.get(Worker, w[0])
        assert x.disputes == 2 and x.revoked_at is not None  # suspended at 2 strikes
        assert db.scalar(select(func.count()).select_from(UsageReceipt)) == 2
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0
        assert all(db.get(Job, i).prompt == "" for i in ids)
