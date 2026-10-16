"""Long-poll, job idempotency, estimate and worker presence, prompt purge, and the project registry."""
import threading
import time

from app.database import SessionLocal
from app.main import app
from app.models import Job, LedgerPosting
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_hardening import H, bal, lease, user, worker

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def test_long_poll_returns_a_job_submitted_while_waiting():
    cons = user(1000)
    w = worker(user())
    t0 = time.monotonic()
    assert TestClient(app).post(f"/workers/{w[0]}/lease?wait=0.6", json={"models": ["m"]}, headers=w[1]).status_code == 204
    assert time.monotonic() - t0 >= 0.5  # it waited
    out = {}
    t = threading.Thread(target=lambda: out.update(r=TestClient(app).post(
        f"/workers/{w[0]}/lease?wait=5", json={"models": ["m"]}, headers=w[1])))
    t0 = time.monotonic()
    t.start()
    time.sleep(0.3)
    jid = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 5}, headers=cons).json()["id"]
    t.join(6)
    assert out["r"].status_code == 200 and out["r"].json()["job_id"] == jid
    assert time.monotonic() - t0 < 4  # returned on arrival, not at the deadline
    assert c.post(f"/workers/{w[0]}/lease?wait=26", json={"models": ["m"]}, headers=w[1]).status_code == 422  # capped


def test_lease_respects_the_worker_token_budget():
    cons = user(1000)
    w = worker(user())
    c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 500}, headers=cons)
    small = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 50}, headers=cons).json()["id"]
    r = c.post(f"/workers/{w[0]}/lease", json={"models": ["m"], "max_tokens": 100}, headers=w[1])
    assert r.json()["job_id"] == small


def test_job_submit_is_idempotent_with_a_key():
    cons = user(1000)
    body = {"model": "m", "prompt": "p", "max_tokens": 100}
    a = c.post("/jobs", json=body, headers={**cons, "Idempotency-Key": "k1"}).json()
    b = c.post("/jobs", json=body, headers={**cons, "Idempotency-Key": "k1"}).json()
    assert a["id"] == b["id"] and bal(cons) == {"available": 900, "held": 100}
    other = user(1000)  # keys are per consumer
    assert c.post("/jobs", json=body, headers={**other, "Idempotency-Key": "k1"}).json()["id"] != a["id"]


def test_estimate_and_worker_presence():
    cons, contrib = user(1000), user()
    w = worker(contrib)
    est = c.get("/estimate", params={"model": "m", "max_tokens": 40}, headers=cons).json()
    assert est == {"max_charge": 40, "price_per_token": 1, "online_workers": 0}
    assert c.get("/workers", headers=contrib).json()[0]["online"] is False
    lease(w)  # a poll marks the worker as seen, with the models it offered
    listed = c.get("/workers", headers=contrib).json()[0]
    assert listed["online"] is True and listed["models"] == ["m"] and listed["jobs_settled"] == 0
    assert c.get("/estimate", params={"model": "m", "max_tokens": 40}, headers=cons).json()["online_workers"] == 1
    assert c.get("/estimate", params={"model": "x", "max_tokens": 40}, headers=cons).json()["online_workers"] == 0
    c.delete(f"/workers/{w[0]}", headers=contrib)
    assert c.get("/estimate", params={"model": "m", "max_tokens": 40}, headers=cons).json()["online_workers"] == 0


def test_prompt_is_dropped_once_the_job_is_terminal():
    cons = user(1000)
    w = worker(user())
    jid = c.post("/jobs", json={"model": "m", "prompt": "private words", "max_tokens": 5}, headers=cons).json()["id"]
    lease(w)
    c.post(f"/jobs/{jid}/result", json={"output": "o", "prompt_tokens": 1, "completion_tokens": 1}, headers=w[1])
    with SessionLocal() as db:
        assert db.get(Job, jid).prompt == ""


def test_project_registry_and_donations():
    maint, donor = user(), user(100)
    p = c.post("/projects", json={"name": "Proj", "url": "https://example.org/p", "description": "d"}, headers=maint).json()
    assert p["verified"] is False and c.get("/projects").json() == []  # unlisted until verified
    assert c.post("/projects", json={"name": "Proj", "url": "https://x.org", "description": "d"}, headers=donor).status_code == 409
    assert c.post("/projects", json={"name": "Bad", "url": "javascript:alert(1)", "description": "d"}, headers=donor).status_code == 422
    don = f"/projects/{p['id']}/donations"
    assert c.post(don, json={"amount": 10}, headers={**donor, "Idempotency-Key": "d1"}).status_code == 404  # not verified
    assert c.post(f"/admin/projects/{p['id']}/verify").status_code == 401
    assert c.post(f"/admin/projects/{p['id']}/verify", headers=ADMIN).status_code == 200
    assert c.post(don, json={"amount": 10}, headers=donor).status_code == 400  # key required
    for _ in range(2):  # retry donates once
        assert c.post(don, json={"amount": 30}, headers={**donor, "Idempotency-Key": "d1"}).json()["budget"] == 30
    assert c.post(don, json={"amount": 71}, headers={**donor, "Idempotency-Key": "d2"}).status_code == 402
    assert bal(donor) == {"available": 70, "held": 0}
    listed = c.get("/projects").json()
    assert [(x["name"], x["budget"], x["verified"]) for x in listed] == [("Proj", 30, True)]
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0


def test_me():
    u = c.post("/users", json={"username": "meuser"}).json()
    assert c.get("/users/me", headers=H(u["api_key"])).json() == {"id": u["id"], "username": "meuser", "oidc": False}


def test_active_workers_per_user_are_capped(monkeypatch):
    from app.routers import workers as wr
    monkeypatch.setattr(wr, "MAX_WORKERS_PER_USER", 2)
    owner = user()
    ids = [c.post("/workers", json={"name": "w"}, headers=owner).json()["id"] for _ in range(2)]
    assert c.post("/workers", json={"name": "w"}, headers=owner).status_code == 409
    c.delete(f"/workers/{ids[0]}", headers=owner)
    assert c.post("/workers", json={"name": "w"}, headers=owner).status_code == 201
