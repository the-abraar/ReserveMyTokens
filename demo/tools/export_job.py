"""Export the ledger postings and signed receipts of two jobs for demo/index.html.

Runs the real coordinator (FastAPI TestClient, throwaway SQLite, alembic head) with a scripted worker that signs
with the real worker module. Both jobs replay judge.md Update 13's real Ollama job: "What is the capital of France?
Answer in one word.", max_tokens 64, Ollama said "Paris" with 41 prompt and 2 completion tokens.
  honest: the worker reports what Ollama said.
  lying:  the worker returns an empty output and claims 64 completion tokens, and signs that claim.
Usage (from the repo root): PYTHONPATH=backend:worker/src python demo/tools/export_job.py > demo/data/jobs.json
"""
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/demo.db"
os.environ["ADMIN_TOKEN"] = "demo-admin"
os.environ.setdefault("RMT_ENV", "dev")

from alembic import command
from alembic.config import Config
from app import receipts
from app.database import SessionLocal
from app.main import app
from app.models import Account, LedgerPosting, LedgerTransaction, User
from fastapi.testclient import TestClient
from reserve_my_tokens_worker import receipts as wreceipts
from sqlalchemy import select

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
cfg = Config(os.path.join(BACKEND, "alembic.ini"))
cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
command.upgrade(cfg, "head")

c = TestClient(app)
H = lambda t: {"Authorization": f"Bearer {t}"}
PROMPT = "What is the capital of France? Answer in one word."


def run(label, result):
    cons = c.post("/users", json={"username": f"consumer-{label}"}).json()
    contrib = c.post("/users", json={"username": f"contributor-{label}"}).json()
    c.post("/admin/fund", json={"user_id": cons["id"], "amount": 1000},
           headers={"X-Admin-Token": "demo-admin", "Idempotency-Key": f"fund-{label}"}).raise_for_status()
    w = c.post("/workers", json={"name": "box"}, headers=H(contrib["api_key"])).json()
    key = wreceipts.new_key()
    c.put(f"/workers/{w['id']}/public_key", json={"public_key": wreceipts.public_key(key)},
          headers=H(w["token"])).raise_for_status()
    jid = c.post("/jobs", json={"model": "qwen2.5:0.5b", "prompt": PROMPT, "max_tokens": 64},
                 headers=H(cons["api_key"])).json()["id"]
    assert c.post(f"/workers/{w['id']}/lease", json={"models": ["qwen2.5:0.5b"]}, headers=H(w["token"])).json()["job_id"] == jid
    res = {**result, "eval_duration_ns": 0, "signature": wreceipts.sign(key, jid, w["id"], {**result, "eval_duration_ns": 0})}
    settled = c.post(f"/jobs/{jid}/result", json=res, headers=H(w["token"])).json()
    rc = c.get(f"/jobs/{jid}/receipt", headers=H(cons["api_key"])).json()
    assert receipts.verify(rc["worker_public_key"], rc["signature"], rc["payload"].encode())
    with SessionLocal() as db:
        rows = db.execute(select(LedgerTransaction.kind, LedgerTransaction.idempotency_key, Account.type, User.username,
                                 LedgerPosting.amount)
                          .join(LedgerPosting, LedgerPosting.tx_id == LedgerTransaction.id)
                          .join(Account, Account.id == LedgerPosting.account_id)
                          .outerjoin(User, User.id == Account.owner_user_id)
                          .where(Account.owner_user_id.in_([cons["id"], contrib["id"]]) | Account.owner_user_id.is_(None),
                                 LedgerTransaction.ref_job_id == jid)
                          .order_by(LedgerPosting.id)).all()
    postings = [{"tx": k, "key": ik, "account": f"{u or 'system'}:{t}", "amount": a} for k, ik, t, u, a in rows]
    for tx in {p["tx"] for p in postings}:
        assert sum(p["amount"] for p in postings if p["tx"] == tx) == 0, tx
    return {"label": label, "job_id": jid, "prompt": PROMPT, "max_tokens": 64, "reported": result,
            "settle_reply": settled, "postings": postings, "receipt": rc,
            "balances": {"consumer": c.get("/users/me/balance", headers=H(cons["api_key"])).json(),
                         "contributor": c.get("/users/me/balance", headers=H(contrib["api_key"])).json()}}


out = [run("honest", {"output": "Paris", "prompt_tokens": 41, "completion_tokens": 2}),
       run("lying", {"output": "", "prompt_tokens": 41, "completion_tokens": 64})]
assert out[0]["settle_reply"]["charged"] == 2 and out[1]["settle_reply"]["charged"] == 64
json.dump(out, sys.stdout, indent=1)
