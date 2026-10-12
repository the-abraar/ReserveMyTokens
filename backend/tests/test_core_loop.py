from app.database import SessionLocal
from app.main import app
from app.models import LedgerPosting, LedgerTransaction
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def H(t):
    return {"Authorization": f"Bearer {t}"}


def test_core_loop():
    with SessionLocal() as db:
        base_tx = db.scalar(select(func.count()).select_from(LedgerTransaction))  # fresh migrated DB: 0, but stay relative
    c = TestClient(app)

    consumer = c.post("/users", json={"username": "consumer"}).json()
    contrib = c.post("/users", json={"username": "contrib"}).json()
    ck, wk = H(consumer["api_key"]), H(contrib["api_key"])
    assert c.post("/admin/fund", json={"user_id": consumer["id"], "amount": 1000}).status_code == 401
    assert c.post("/admin/fund", json={"user_id": consumer["id"], "amount": 1000},
                  headers={"X-Admin-Token": "test-admin", "Idempotency-Key": "k1"}).status_code == 200

    w = c.post("/workers", json={"name": "box"}, headers=wk).json()
    wt = H(w["token"])

    # insufficient funds rejected, nothing reserved
    assert c.post("/jobs", json={"model": "m", "prompt": "hi", "max_tokens": 5000}, headers=ck).status_code == 422
    assert c.post("/jobs", json={"model": "m", "prompt": "hi", "max_tokens": 2000}, headers=ck).status_code == 402
    assert c.get("/users/me/balance", headers=ck).json() == {"available": 1000, "held": 0}

    job = c.post("/jobs", json={"model": "m", "prompt": "hi", "max_tokens": 100}, headers=ck).json()
    assert c.get("/users/me/balance", headers=ck).json() == {"available": 900, "held": 100}
    assert c.get(f"/jobs/{job['id']}", headers=wk).status_code == 404  # authz isolation

    assert c.post(f"/workers/{w['id']}/lease", json={"models": ["other"]}, headers=wt).status_code == 204
    leased = c.post(f"/workers/{w['id']}/lease", json={"models": ["m"]}, headers=wt).json()
    assert leased["job_id"] == job["id"]
    assert c.post(f"/workers/{w['id']}/lease", json={"models": ["m"]}, headers=wt).status_code == 204

    res = {"output": "hello", "prompt_tokens": 3, "completion_tokens": 40, "eval_duration_ns": 5}
    r1 = c.post(f"/jobs/{job['id']}/result", json=res, headers=wt).json()
    r2 = c.post(f"/jobs/{job['id']}/result", json=res, headers=wt).json()  # retry
    assert r1["settled"] is True and r2["settled"] is False

    assert c.get("/users/me/balance", headers=ck).json() == {"available": 960, "held": 0}
    assert c.get("/users/me/balance", headers=wk).json() == {"available": 40, "held": 0}
    done = c.get(f"/jobs/{job['id']}", headers=ck).json()
    assert done["status"] == "completed" and done["output"] == "hello"

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "settle")) == 1
        sums = db.execute(select(LedgerPosting.tx_id, func.sum(LedgerPosting.amount)).group_by(LedgerPosting.tx_id)).all()
        assert len(sums) - base_tx == 3 and all(s == 0 for _, s in sums)  # fund, reserve, settle
        assert db.scalar(select(func.sum(LedgerPosting.amount))) == 0

    # revoked worker is locked out
    assert c.delete(f"/workers/{w['id']}", headers=wk).status_code == 204
    assert c.post(f"/workers/{w['id']}/lease", json={"models": ["m"]}, headers=wt).status_code == 401
