"""End to end over real HTTP: CLI worker -> coordinator (uvicorn subprocess) -> ledger -> the dashboard's API calls.

Ollama is NOT installed on the dev machine, so `FakeOllama` speaks its HTTP API (/api/tags, /api/generate); the real
OllamaAdapter talks to it over HTTP. The coordinator uses this test's database (SQLite file, or TEST_DATABASE_URL)."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyring
import pytest
import requests
from app import database, receipts
from app.models import Job, LedgerPosting, LedgerTransaction, UsageReceipt
from click.testing import CliRunner
from reserve_my_tokens_worker import cli
from reserve_my_tokens_worker import receipts as wr
from reserve_my_tokens_worker.limits import Limits
from reserve_my_tokens_worker.polling_client import CoordinatorClient
from reserve_my_tokens_worker.provider import ModelProvider
from sqlalchemy import func, select
from test_oidc import stub_login

BACKEND = os.path.join(os.path.dirname(__file__), "..")
PROMPT, OUTPUT = "SECRET-PROMPT-7f3a summarise this", "OUTPUT-9b2c here is the summary"
ADMIN = {"X-Admin-Token": "test-admin"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):  # the real Ollama logs nothing per request by default either
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"models": [{"name": "tiny:1b"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send({"response": OUTPUT, "prompt_eval_count": len(req["prompt"].split()),
                    "eval_count": min(7, req["options"]["num_predict"]), "eval_duration": 1000})


class MemKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        self.d.pop((s, u))


@pytest.fixture
def stack(tmp_path):
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DATABASE_URL": database.engine.url.render_as_string(hide_password=False), "RMT_ENV": "dev",
           "OIDC_STUB": "1", "OIDC_ISSUER": f"{base}/oidc-stub", "ADMIN_TOKEN": "test-admin", "SWEEP_INTERVAL_SECONDS": "1",
           "RATE_SUBMIT_PER_MIN": "1000", "RATE_LEASE_PER_MIN": "100000"}
    with open(tmp_path / "server.log", "w") as log:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "debug"],
                                cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
        ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=ollama.serve_forever, daemon=True).start()
        old_kr = keyring.get_keyring()
        keyring.set_keyring(MemKeyring())
        try:
            for _ in range(100):
                try:
                    if requests.get(base, timeout=1).ok:
                        break
                except requests.ConnectionError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("coordinator did not start: " + (tmp_path / "server.log").read_text())
            yield {"base": base, "ollama": f"http://127.0.0.1:{ollama.server_port}", "log": tmp_path / "server.log", "tmp": tmp_path}
        finally:
            keyring.set_keyring(old_kr)
            ollama.shutdown()
            proc.terminate()
            proc.wait(10)


def H(t):
    return {"Authorization": f"Bearer {t}"}


def wait_for(fn, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if v := fn():
            return v
        time.sleep(0.1)
    raise AssertionError("timed out")


def ledger_is_balanced():
    with database.SessionLocal() as db:
        per_tx = db.execute(select(LedgerPosting.tx_id, func.sum(LedgerPosting.amount)).group_by(LedgerPosting.tx_id)).all()
        return all(s == 0 for _, s in per_tx) and db.scalar(select(func.sum(LedgerPosting.amount))) == 0


def test_cli_to_coordinator_to_ledger_to_dashboard(stack, caplog):
    caplog.set_level("DEBUG")
    base = stack["base"]
    http = requests.Session()
    # Consumer logs in with OIDC (stub issuer; the coordinator fetches its JWKS over HTTP).
    tok = stub_login(http, "consumer", base=base, redirect_kw={"allow_redirects": False}).json()["id_token"]
    cons = H(tok)
    cons_id = http.get(f"{base}/users/me", headers=cons).json()["id"]
    assert http.post(f"{base}/admin/fund", json={"user_id": cons_id, "amount": 1000},
                     headers={**ADMIN, "Idempotency-Key": "seed"}).ok
    # Contributor uses an API key, registers a worker on the dashboard, and logs the CLI in (token -> keychain).
    contrib = H(http.post(f"{base}/users", json={"username": "contrib"}).json()["api_key"])
    w = http.post(f"{base}/workers", json={"name": "laptop"}, headers=contrib).json()
    common = ["--worker-id", str(w["id"]), "--coordinator-url", base]
    r = CliRunner().invoke(cli.main, ["login", *common], input=w["token"] + "\n")
    assert r.exit_code == 0, r.output
    kill = stack["tmp"] / "STOP"
    run = {}
    t = threading.Thread(target=lambda: run.update(r=CliRunner().invoke(cli.main, [
        "start", *common, "--ollama-url", stack["ollama"], "--wait", "2", "--kill-file", str(kill)])))
    t.start()
    try:
        wait_for(lambda: http.get(f"{base}/workers", headers=contrib).json()[0]["online"])
        est = http.get(f"{base}/estimate", params={"model": "tiny:1b", "max_tokens": 50}, headers=cons).json()
        assert est == {"max_charge": 50, "price_per_token": 1, "online_workers": 1}

        body = {"model": "tiny:1b", "prompt": PROMPT, "max_tokens": 50}
        job = http.post(f"{base}/jobs", json=body, headers={**cons, "Idempotency-Key": "j1"}).json()
        assert http.post(f"{base}/jobs", json=body, headers={**cons, "Idempotency-Key": "j1"}).json()["id"] == job["id"]
        done = wait_for(lambda: (j := http.get(f"{base}/jobs/{job['id']}", headers=cons).json())["status"] == "completed" and j)
        assert done["output"] == OUTPUT
    finally:
        kill.touch()  # kill switch: the worker stops after its current long-poll
        t.join(10)
    assert not t.is_alive() and run["r"].exit_code == 0, run.get("r") and run["r"].output

    # Dashboard views (the same calls web/app makes).
    assert http.get(f"{base}/users/me/balance", headers=cons).json() == {"available": 993, "held": 0}
    assert http.get(f"{base}/users/me/balance", headers=contrib).json() == {"available": 7, "held": 0}
    wl = http.get(f"{base}/workers", headers=contrib).json()[0]
    assert wl["jobs_settled"] == 1 and wl["signing_key"] is True and wl["models"] == ["tiny:1b"]
    rc = http.get(f"{base}/jobs/{job['id']}/receipt", headers=cons).json()
    assert rc["signed"] and rc["charged"] == 7 and receipts.verify(rc["worker_public_key"], rc["signature"], rc["payload"].encode())

    # Donation registry: the contributor gives part of what they earned to a verified project.
    p = http.post(f"{base}/projects", json={"name": "OSS", "url": "https://example.org", "description": "d"}, headers=contrib).json()
    assert http.post(f"{base}/admin/projects/{p['id']}/verify", headers=ADMIN).ok
    assert http.post(f"{base}/projects/{p['id']}/donations", json={"amount": 3},
                     headers={**contrib, "Idempotency-Key": "don1"}).json()["budget"] == 3
    assert [x["budget"] for x in http.get(f"{base}/projects").json()] == [3]
    assert http.get(f"{base}/users/me/balance", headers=contrib).json()["available"] == 4

    # Ledger: every transaction balances; the job settled once; the prompt is gone from the database.
    assert ledger_is_balanced()
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "settle")) == 1
        assert db.get(Job, job["id"]).prompt == ""

    # Boundary C: neither the coordinator's log (debug level) nor the worker's logs contain the prompt or the output.
    worker_logs = caplog.text + run["r"].output
    for text in (stack["log"].read_text(), worker_logs):
        assert PROMPT not in text and OUTPUT not in text and w["token"] not in text
    assert "leased job" in worker_logs and "POST /jobs" in stack["log"].read_text()  # both logs were captured


class Dummy(ModelProvider):
    """A dummy contributor node: no model, deterministic output, fixed usage."""
    name = "dummy"

    def detect_models(self):
        return ["dummy"]

    def run_inference(self, model, prompt, max_tokens, temperature=0):
        return {"output": "ok", "prompt_tokens": 1, "completion_tokens": 5, "eval_duration_ns": 1}


def test_pilot_simulation_10_contributors_2_consumers(stack):
    base, http = stack["base"], requests.Session()
    consumers = []
    for i in range(2):
        u = http.post(f"{base}/users", json={"username": f"consumer{i}"}).json()
        http.post(f"{base}/admin/fund", json={"user_id": u["id"], "amount": 500}, headers={**ADMIN, "Idempotency-Key": f"c{i}"})
        consumers.append(H(u["api_key"]))
    owners, threads, kill = [], [], stack["tmp"] / "STOP-ALL"
    for i in range(10):
        owner = H(http.post(f"{base}/users", json={"username": f"node{i}"}).json()["api_key"])
        wk = http.post(f"{base}/workers", json={"name": f"node{i}"}, headers=owner).json()
        key = wr.new_key()
        client = CoordinatorClient(base, wk["id"], wk["token"], poll_interval=0.2, signing_key=key, wait=1,
                                   limits=Limits(kill_file=kill))
        client.register_key(wr.public_key(key))
        owners.append(owner)
        threads.append(threading.Thread(target=client.start_polling, args=(Dummy(), ["dummy"])))
    for t in threads:
        t.start()
    jobs = []
    try:
        for n in range(10):
            for ci, ch in enumerate(consumers):
                jobs.append((ch, http.post(f"{base}/jobs", json={"model": "dummy", "prompt": f"task {ci}-{n}", "max_tokens": 20},
                                           headers={**ch, "Idempotency-Key": f"{ci}-{n}"}).json()["id"]))
        wait_for(lambda: all(http.get(f"{base}/jobs/{j}", headers=ch).json()["status"] == "completed" for ch, j in jobs), 60)
    finally:
        kill.touch()
        for t in threads:
            t.join(10)
    assert not any(t.is_alive() for t in threads)
    spent = sum(500 - http.get(f"{base}/users/me/balance", headers=ch).json()["available"] for ch in consumers)
    earned = [http.get(f"{base}/users/me/balance", headers=o).json()["available"] for o in owners]
    assert spent == sum(earned) == 20 * 5  # what consumers paid is exactly what contributors earned
    with database.SessionLocal() as db:
        receipts_rows = db.scalars(select(UsageReceipt)).all()
        settles = db.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "settle"))
    assert len(receipts_rows) == settles == 20 and sum(r.charged for r in receipts_rows) == spent
    assert sum(1 for e in earned if e) >= 2  # work was spread over several nodes, not one
    assert ledger_is_balanced()
