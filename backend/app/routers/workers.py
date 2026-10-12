from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import current_user, current_worker, new_token
from ..database import get_db
from ..models import Job, JobAttempt, User, Worker
from ..models.ledger import now
from ..ratelimit import limit
from .jobs import release_reservation

router = APIRouter()
LEASE_TTL = timedelta(seconds=120)


class NewWorker(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class LeaseReq(BaseModel):
    models: list[str] = Field(min_length=1, max_length=100)


@router.post("/workers", status_code=201)
def register_worker(body: NewWorker, u: User = Depends(current_user), db: Session = Depends(get_db)):
    token, h = new_token()
    w = Worker(owner_user_id=u.id, name=body.name, token_hash=h)
    db.add(w)
    db.commit()
    return {"id": w.id, "token": token}  # shown once


@router.get("/workers")
def list_workers(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": w.id, "name": w.name, "revoked": w.revoked_at is not None, "created_at": w.created_at.isoformat()}
            for w in db.scalars(select(Worker).where(Worker.owner_user_id == u.id).order_by(Worker.id))]


def reap_expired(db: Session, t):
    """Expired lease -> back to queue; after max_attempts -> terminal 'failed' and the reservation is refunded.
    Called on each lease and by the background sweeper (app.main lifespan)."""
    for j in db.scalars(select(Job).where(Job.status == "leased", Job.lease_expires_at < t)):
        n = db.scalar(select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == j.id))
        new = "failed" if n >= j.max_attempts else "queued"
        r = db.execute(update(Job).where(Job.id == j.id, Job.status == "leased", Job.lease_expires_at < t)
                       .values(status=new, worker_id=None, lease_expires_at=None), execution_options={"synchronize_session": False})
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


@router.post("/workers/{worker_id}/lease", dependencies=[Depends(limit("lease"))])
def lease(worker_id: int, body: LeaseReq, w: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    """Short poll (204 = nothing). shortcut: no long-poll, add before pilot."""
    if w.id != worker_id:
        raise HTTPException(403, "token is for a different worker")
    t = now()
    reap_expired(db, t)
    # Same OWNER (not just same worker id) may not verify its own run; owners can register unlimited workers.
    done_by_me = (select(JobAttempt.job_id).join(Worker, Worker.id == JobAttempt.worker_id)
                  .where(Worker.owner_user_id == w.owner_user_id, JobAttempt.output.is_not(None)))
    own_redundant = select(Job.id).where(Job.redundant.is_(True), Job.consumer_user_id == w.owner_user_id)  # consumer can't self-verify
    for _ in range(5):  # retry if another worker wins the race
        cand = db.scalar(
            select(Job.id)
            .where(Job.model.in_(body.models),
                   Job.status == "queued", Job.id.not_in(done_by_me), Job.id.not_in(own_redundant))  # a redundant run needs a different worker
            .order_by(Job.id).limit(1)
            .with_for_update(skip_locked=True))  # no-op on SQLite
        if cand is None:
            return Response(status_code=204)
        exp = t + LEASE_TTL
        # compare-and-set: correct even where FOR UPDATE does not exist (SQLite)
        r = db.execute(update(Job).where(Job.id == cand,
                       Job.status == "queued", Job.id.not_in(done_by_me), Job.id.not_in(own_redundant))  # a redundant run needs a different worker
                       .values(status="leased", worker_id=w.id, lease_expires_at=exp))
        if r.rowcount == 1:
            db.add(JobAttempt(job_id=cand, worker_id=w.id, lease_expires_at=exp))
            db.commit()
            j = db.get(Job, cand)
            return {"job_id": j.id, "model": j.model, "prompt": j.prompt, "max_tokens": j.max_tokens, "temperature": j.temperature,
                    "lease_expires_at": exp.isoformat()}
        db.rollback()
    return Response(status_code=204)
