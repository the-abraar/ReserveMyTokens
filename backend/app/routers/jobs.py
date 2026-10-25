import os
import random

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import receipts
from ..auth import current_user, current_worker
from ..database import get_db
from ..ledger import InsufficientFunds, post, spend
from ..models import Job, JobAttempt, UsageReceipt, User, Worker
from ..models.ledger import now
from ..ratelimit import limit
from .users import user_account

router = APIRouter()
PRICE_PER_TOKEN = 1  # test credits per completion token


class NewJob(BaseModel):
    model: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20000)
    max_tokens: int = Field(ge=1, le=4096)
    temperature: float = Field(ge=0, le=2, default=0)


class Result(BaseModel):
    output: str = Field(max_length=200000)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    eval_duration_ns: int = Field(ge=0, default=0)
    signature: str | None = Field(None, max_length=200)  # required once the worker registered a public key


def view(j: Job):
    return {"id": j.id, "status": j.status, "model": j.model, "max_tokens": j.max_tokens,
            "reserved": j.reserved, "output": j.output, "created_at": j.created_at.isoformat()}


def release_reservation(db: Session, j: Job):
    """Refund the whole reservation to the consumer (job failed/disputed). Balanced and idempotent."""
    held, avail = user_account(db, j.consumer_user_id, "user_held").id, user_account(db, j.consumer_user_id, "user_available").id
    post(db, "refund", f"job:{j.id}:refund", [(held, -j.reserved), (avail, j.reserved)], j.id)


def strike(db: Session, wid: int):
    """One dispute strike; suspends the worker at DISPUTE_SUSPEND_AFTER."""
    x = db.get(Worker, wid)
    x.disputes = (x.disputes or 0) + 1
    if x.disputes >= int(os.getenv("DISPUTE_SUSPEND_AFTER", "3")) and not x.revoked_at:
        x.revoked_at = now()


def verifier_pct() -> int:
    """REDUNDANCY_VERIFIER_PCT (0-100, default 0): share of the charge paid to the second worker whose
    matching re-run verified the result; the first worker keeps the rest. Funded out of the worker payout."""
    return max(0, min(100, int(os.getenv("REDUNDANCY_VERIFIER_PCT", "0"))))


def redundancy_prob() -> float:
    return float(os.getenv("REDUNDANCY_PROB", "0"))  # default off


@router.get("/jobs")
def list_jobs(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [view(j) for j in db.scalars(select(Job).where(Job.consumer_user_id == u.id).order_by(Job.id.desc()).limit(50))]


@router.post("/jobs", status_code=201, dependencies=[Depends(limit("submit"))])
def create_job(body: NewJob, idempotency_key: str = Header("", max_length=200), u: User = Depends(current_user),
               db: Session = Depends(get_db)):
    """An Idempotency-Key header makes a retried submit return the first job instead of reserving twice."""
    key = idempotency_key.strip() or None
    same = select(Job).where(Job.consumer_user_id == u.id, Job.idempotency_key == key)
    if key and (prior := db.scalar(same)):
        return view(prior)
    avail, held = user_account(db, u.id, "user_available"), user_account(db, u.id, "user_held")
    j = Job(consumer_user_id=u.id, model=body.model, prompt=body.prompt, max_tokens=body.max_tokens, idempotency_key=key,
            reserved=body.max_tokens * PRICE_PER_TOKEN, temperature=body.temperature,
            # Redundancy only for temperature 0: sampled outputs legitimately differ, so exact match is meaningless.
            redundant=body.temperature == 0 and random.random() < redundancy_prob())
    db.add(j)
    try:
        db.flush()
    except IntegrityError:  # a concurrent retry with the same key got there first
        db.rollback()
        return view(db.scalar(same))
    try:
        spend(db, avail.id, held.id, j.reserved, "reserve", f"job:{j.id}:reserve", j.id)
    except InsufficientFunds:
        db.rollback()
        raise HTTPException(402, "insufficient credits")
    db.commit()
    return view(j)


@router.get("/jobs/{job_id}")
def get_job(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j or j.consumer_user_id != u.id:
        raise HTTPException(404, "not found")
    return view(j)


@router.get("/jobs/{job_id}/receipt")
def get_receipt(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Auth: the job's consumer. `payload` is what the worker signed; check it with `worker_public_key` (Ed25519)."""
    j = db.get(Job, job_id)
    rc = j and j.consumer_user_id == u.id and db.scalar(select(UsageReceipt).where(UsageReceipt.job_id == job_id))
    if not rc:
        raise HTTPException(404, "not found")
    att, w = db.get(JobAttempt, rc.attempt_id), db.get(Worker, rc.worker_id)
    data = receipts.payload(j.id, w.id, att.output or "", rc.prompt_tokens, rc.completion_tokens, rc.eval_duration_ns)
    return {"job_id": j.id, "worker_id": w.id, "model": j.model, "prompt_tokens": rc.prompt_tokens,
            "completion_tokens": rc.completion_tokens, "eval_duration_ns": rc.eval_duration_ns, "charged": rc.charged,
            "usage_source": "worker_reported", "signed": bool(att.signature), "signature": att.signature,
            "worker_public_key": w.public_key, "payload": data.decode(), "created_at": rc.created_at.isoformat()}


@router.post("/jobs/{job_id}/result")
def submit_result(job_id: int, body: Result, w: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j or j.worker_id != w.id:
        raise HTTPException(404, "not found")
    if j.status == "completed":
        return {"status": "completed", "settled": False}  # idempotent replay
    data = receipts.payload(j.id, w.id, body.output, body.prompt_tokens, body.completion_tokens, body.eval_duration_ns)
    if w.public_key and not receipts.verify(w.public_key, body.signature, data):  # checked before the job is claimed
        raise HTTPException(400, "missing or invalid receipt signature")
    att = db.scalar(select(JobAttempt).where(JobAttempt.job_id == j.id, JobAttempt.worker_id == w.id)
                    .order_by(JobAttempt.id.desc()))
    # First finished run of a redundant job, if any, from a different worker.
    other = db.scalar(select(JobAttempt).join(Worker, Worker.id == JobAttempt.worker_id)
                      .where(JobAttempt.job_id == j.id, Worker.owner_user_id != w.owner_user_id,
                             JobAttempt.output.is_not(None))) if j.redundant else None
    agree = other is not None and other.output == body.output
    new_status = "queued" if j.redundant and not other else "disputed" if other and not agree else "completed"
    # Claim with compare-and-set: only one concurrent submit can move the job out of leased.
    r = db.execute(update(Job).where(Job.id == job_id, Job.status == "leased", Job.worker_id == w.id)
                   .values(status=new_status, output=body.output if new_status == "completed" else None,
                           **({} if new_status == "queued" else {"prompt": ""}),  # Boundary C: drop the prompt once terminal
                           **({"worker_id": None, "lease_expires_at": None} if new_status == "queued" else {})))
    if r.rowcount != 1:
        return {"status": j.status, "settled": False}
    att.output, att.prompt_tokens, att.completion_tokens, att.eval_duration_ns, att.signature = (
        body.output, body.prompt_tokens, body.completion_tokens, body.eval_duration_ns, body.signature)
    if j.expected_output is not None:  # probe: grade, never pay (no reservation, no receipt, no ledger)
        passed = body.output == j.expected_output and body.completion_tokens == j.expected_tokens
        if not passed:
            att.flagged = True
            strike(db, w.id)
        db.commit()
        return {"status": "completed", "settled": False}  # same reply as an unpaid job: the worker cannot tell a probe
    if new_status == "queued":  # wait for a second, different worker (lease skips workers with a finished attempt)
        db.commit()
        return {"status": "awaiting_verification", "settled": False}
    if new_status == "disputed":  # no payout; flag both runs for review; consumer gets the reservation back
        att.flagged = other.flagged = True
        # shortcut: mitigation only; we can't tell which side lied, so both take a strike. Sybil owners can still re-register.
        for wid in (att.worker_id, other.worker_id):
            strike(db, wid)
        release_reservation(db, j)
        db.commit()
        return {"status": "disputed", "settled": False}
    # Redundant and agreed: pay the first worker, on the lower of the two self-reported token counts.
    pay_att = other or att
    tokens = min(body.completion_tokens, other.completion_tokens) if other else body.completion_tokens
    payee = db.get(Worker, pay_att.worker_id)
    # shortcut: charge worker-reported tokens capped at the reservation; server-side metering is unsolved.
    charge = min(tokens, j.max_tokens) * PRICE_PER_TOKEN
    held = user_account(db, j.consumer_user_id, "user_held").id
    consumer = user_account(db, j.consumer_user_id, "user_available").id
    earner = user_account(db, payee.owner_user_id, "user_available").id
    vshare = charge * verifier_pct() // 100 if other else 0
    verifier = user_account(db, w.owner_user_id, "user_available").id
    tx = post(db, "settle", f"job:{j.id}:settle",
              [(held, -j.reserved), (earner, charge - vshare), (verifier, vshare), (consumer, j.reserved - charge)], j.id)  # platform fee = 0
    db.add(UsageReceipt(job_id=j.id, attempt_id=pay_att.id, worker_id=payee.id, prompt_tokens=pay_att.prompt_tokens or 0,
                        completion_tokens=pay_att.completion_tokens or 0, eval_duration_ns=pay_att.eval_duration_ns or 0,
                        charged=charge, tx_id=tx.id))
    db.commit()
    return {"status": "completed", "settled": True, "charged": charge}
