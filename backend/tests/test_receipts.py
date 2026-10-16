"""Signed usage receipts. Signs with the real worker module, so a drift between the two payload formats fails here."""
from app import receipts
from app.main import app
from app.routers.jobs import Result
from fastapi.testclient import TestClient
from reserve_my_tokens_worker import receipts as wreceipts
from reserve_my_tokens_worker.provider import RESULT_KEYS
from test_hardening import bal, lease, user, worker

c = TestClient(app)


def test_worker_and_coordinator_agree_on_format():
    assert receipts.payload(1, 2, "outé", 3, 4, 5) == wreceipts.payload(1, 2, "outé", 3, 4, 5)
    assert set(Result.model_fields) == RESULT_KEYS | {"signature"}


def test_signed_result_settles_and_receipt_verifies():
    cons, contrib = user(1000), user()
    w = worker(contrib)
    key = wreceipts.new_key()
    put = lambda k: c.put(f"/workers/{w[0]}/public_key", json={"public_key": k}, headers=w[1])
    assert put("not-a-key").status_code == 400
    assert put(wreceipts.public_key(key)).status_code == 200
    assert put(wreceipts.public_key(key)).status_code == 200  # same key again: idempotent
    assert put(wreceipts.public_key(wreceipts.new_key())).status_code == 409  # no silent rotation

    jid = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 50}, headers=cons).json()["id"]
    assert lease(w).json()["job_id"] == jid
    res = {"output": "hello", "prompt_tokens": 2, "completion_tokens": 20, "eval_duration_ns": 7}
    url = f"/jobs/{jid}/result"
    assert c.post(url, json=res, headers=w[1]).status_code == 400  # unsigned, but the worker has a key
    inflated = {**res, "completion_tokens": 50, "signature": wreceipts.sign(key, jid, w[0], res)}
    assert c.post(url, json=inflated, headers=w[1]).status_code == 400  # signature does not cover these numbers
    assert c.get(f"/jobs/{jid}", headers=cons).json()["status"] == "leased"  # rejected submits did not claim the job
    assert c.post(url, json={**res, "signature": wreceipts.sign(key, jid, w[0], res)}, headers=w[1]).json()["settled"] is True
    assert bal(contrib)["available"] == 20

    rc = c.get(f"/jobs/{jid}/receipt", headers=cons).json()
    assert rc["signed"] is True and rc["charged"] == 20 and rc["usage_source"] == "worker_reported"
    assert receipts.verify(rc["worker_public_key"], rc["signature"], rc["payload"].encode())
    assert c.get(f"/jobs/{jid}/receipt", headers=contrib).status_code == 404  # only the consumer sees it


def test_unsigned_worker_still_works_and_receipt_says_so():
    cons, contrib = user(1000), user()
    w = worker(contrib)
    jid = c.post("/jobs", json={"model": "m", "prompt": "p", "max_tokens": 10}, headers=cons).json()["id"]
    lease(w)
    c.post(f"/jobs/{jid}/result", json={"output": "o", "prompt_tokens": 1, "completion_tokens": 3}, headers=w[1])
    rc = c.get(f"/jobs/{jid}/receipt", headers=cons).json()
    assert rc["signed"] is False and rc["signature"] is None
