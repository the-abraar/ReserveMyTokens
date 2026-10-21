import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import current_user, current_worker, new_token
from ..database import get_db
from ..models import Job, JobAttempt, UsageReceipt, User, Worker
from ..models.ledger import now
from ..ratelimit import limit
from ..receipts import valid_public_key
from .jobs import PRICE_PER_TOKEN, release_reservation

router = APIRouter()
LEASE_TTL = timedelta(seconds=120)
ONLINE_WINDOW = timedelta(seconds=90)  # longer than the longest long-poll (25 s) plus client back-off
LONG_POLL_STEP = 0.5  # seconds between queue checks while a long-poll waits
MAX_WORKERS_PER_USER = 20  # active (unrevoked) workers; CODING_STANDARDS "Cap"


class NewWorker(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class LeaseReq(BaseModel):
    models: list[str] = Field(min_length=1, max_length=100)
    max_tokens: int | None = Field(None, ge=1, le=4096)  # worker's remaining local budget: only smaller jobs are offered


class PublicKey(BaseModel):
    public_key: str = Field(min_length=1, max_length=100)


def online(w: Worker, t) -> bool:
    return w.revoked_at is None and w.last_seen_at is not None and t - w.last_seen_at < ONLINE_WINDOW


@router.get("/estimate")
def estimate(model: str = Query(min_length=1, max_length=100), max_tokens: int = Query(ge=1, le=4096),
             u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Auth: any user. Server-side price: the most a job can cost is its reservation (unused tokens are refunded)."""
    t = now()
    seen = db.scalars(select(Worker).where(Worker.revoked_at.is_(None), Worker.last_seen_at >= t - ONLINE_WINDOW).limit(1000))
    return {"max_charge": max_tokens * PRICE_PER_TOKEN, "price_per_token": PRICE_PER_TOKEN,
            "online_workers": sum(1 for w in seen if online(w, t) and model in (w.models or "").split(","))}


@router.post("/workers", status_code=201)
def register_worker(body: NewWorker, u: User = Depends(current_user), db: Session = Depends(get_db)):
    active = select(func.count()).select_from(Worker).where(Worker.owner_user_id == u.id, Worker.revoked_at.is_(None))
    if db.scalar(active) >= MAX_WORKERS_PER_USER:
        raise HTTPException(409, f"at most {MAX_WORKERS_PER_USER} active workers per user; revoke one first")
    token, h = new_token()
    w = Worker(owner_user_id=u.id, name=body.name, token_hash=h)
    db.add(w)
    db.commit()
    return {"id": w.id, "token": token}  # shown once


@router.get("/workers")
def list_workers(u: User = Depends(current_user), db: Session = Depends(get_db)):
    t = now()
    done = dict(db.execute(select(UsageReceipt.worker_id, func.count()).join(Worker, Worker.id == UsageReceipt.worker_id)
                           .where(Worker.owner_user_id == u.id).group_by(UsageReceipt.worker_id)).all())
    return [{"id": w.id, "name": w.name, "revoked": w.revoked_at is not None, "created_at": w.created_at.isoformat(),
             "online": online(w, t), "last_seen_at": w.last_seen_at and w.last_seen_at.isoformat(),
             "models": w.models.split(",") if w.models else [], "signing_key": w.public_key is not None,
             "jobs_settled": done.get(w.id, 0)}
            for w in db.scalars(select(Worker).where(Worker.owner_user_id == u.id).order_by(Worker.id).limit(200))]


def reap_expired(db: Session, t):
    """Expired lease -> back to queue; after max_attempts -> terminal 'failed' and the reservation is refunded.
    Called on each lease and by the background sweeper (app.main lifespan)."""
    for j in db.scalars(select(Job).where(Job.status == "leased", Job.lease_expires_at < t)):
        n = db.scalar(select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == j.id))
        new = "failed" if n >= j.max_attempts else "queued"
        r = db.execute(update(Job).where(Job.id == j.id, Job.status == "leased", Job.lease_expires_at < t)
                       .values(status=new, worker_id=None, lease_expires_at=None,
                               **({"prompt": ""} if new == "failed" else {})),  # Boundary C: drop the prompt once terminal
                       execution_options={"synchronize_session": False})
        if r.rowcount == 1 and new == "failed":
            release_reservation(db, j)
    db.commit()


@router.delete("/workers/{worker_id}", status_code=204)
def revoke_worker(worker_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    w = db.get(Worker, worker_id)
    if not w or w.owner_user_id != u.id:
        raise HTTPException(404, "not found")
    w.revoked_at = w.revoked_at or now()
    db.commit()


@router.put("/workers/{worker_id}/public_key")
def set_public_key(worker_id: int, body: PublicKey, w: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    """Auth: the worker's own token. Set once (compare-and-set); to rotate, register a new worker."""
    if w.id != worker_id:
        raise HTTPException(403, "token is for a different worker")
    if not valid_public_key(body.public_key):
        raise HTTPException(400, "not a base64 Ed25519 public key")
    r = db.execute(update(Worker).where(Worker.id == w.id, Worker.public_key.is_(None)).values(public_key=body.public_key))
    db.commit()
    if r.rowcount != 1 and db.scalar(select(Worker.public_key).where(Worker.id == w.id)) != body.public_key:
        raise HTTPException(409, "worker already has a different key")
    return {"ok": True}


def _try_lease(db: Session, w_id: int, owner: int, body: LeaseReq, t):
    # Same OWNER (not just same worker id) may not verify its own run; owners can register unlimited workers.
    done_by_me = (select(JobAttempt.job_id).join(Worker, Worker.id == JobAttempt.worker_id)
                  .where(Worker.owner_user_id == owner, JobAttempt.output.is_not(None)))
    own_redundant = select(Job.id).where(Job.redundant.is_(True), Job.consumer_user_id == owner)  # consumer can't self-verify
    fits = [Job.max_tokens <= body.max_tokens] if body.max_tokens else []
    for _ in range(5):  # retry if another worker wins the race
        cand = db.scalar(
            select(Job.id)
            .where(Job.model.in_(body.models), *fits,
                   Job.status == "queued", Job.id.not_in(done_by_me), Job.id.not_in(own_redundant))  # a redundant run needs a different worker
            .order_by(Job.id).limit(1)
            .with_for_update(skip_locked=True))  # no-op on SQLite
        if cand is None:
            return None
        exp = t + LEASE_TTL
        # compare-and-set: correct even where FOR UPDATE does not exist (SQLite)
        r = db.execute(update(Job).where(Job.id == cand,
                       Job.status == "queued", Job.id.not_in(done_by_me), Job.id.not_in(own_redundant))  # a redundant run needs a different worker
                       .values(status="leased", worker_id=w_id, lease_expires_at=exp))
        if r.rowcount == 1:
            db.add(JobAttempt(job_id=cand, worker_id=w_id, lease_expires_at=exp))
            db.commit()
            j = db.get(Job, cand)
            return {"job_id": j.id, "model": j.model, "prompt": j.prompt, "max_tokens": j.max_tokens, "temperature": j.temperature,
                    "lease_expires_at": exp.isoformat()}
        db.rollback()
    return None


@router.post("/workers/{worker_id}/lease", dependencies=[Depends(limit("lease"))])
def lease(worker_id: int, body: LeaseReq, wait: float = Query(0, ge=0, le=25),
          w: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    """Long poll: waits up to `wait` seconds for a job (204 = nothing). wait=0 is a short poll.
    shortcut: holds a threadpool thread and re-queries every LONG_POLL_STEP; use LISTEN/NOTIFY or async past ~30 workers per process."""
    if w.id != worker_id:
        raise HTTPException(403, "token is for a different worker")
    w_id, owner = w.id, w.owner_user_id
    w.last_seen_at, w.models = now(), ",".join(body.models)[:2000]
    db.commit()
    reap_expired(db, now())
    deadline = time.monotonic() + wait
    while True:
        job = _try_lease(db, w_id, owner, body, now())
        if job:
            return job
        db.rollback()  # end the read transaction so the next pass sees new jobs
        if time.monotonic() >= deadline:
            return Response(status_code=204)
        time.sleep(LONG_POLL_STEP)
