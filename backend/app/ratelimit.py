"""Per-token (or per-client-IP) fixed-window rate limit, counted in the database so every API process shares one limit."""
import os
import time

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import hash_token
from .database import get_db

LIMITS = {"submit": int(os.getenv("RATE_SUBMIT_PER_MIN", "30")), "lease": int(os.getenv("RATE_LEASE_PER_MIN", "120")),
          "signup": int(os.getenv("RATE_SIGNUP_PER_MIN", "5")), "project": int(os.getenv("RATE_PROJECT_PER_MIN", "5"))}

# Atomic upsert on Postgres and SQLite >= 3.35: a new minute resets the row's counter.
_HIT = text("""INSERT INTO rate_hits (bucket, key_hash, minute, hits) VALUES (:b, :k, :m, 1)
ON CONFLICT (bucket, key_hash) DO UPDATE
SET hits = CASE WHEN rate_hits.minute = :m THEN rate_hits.hits + 1 ELSE 1 END, minute = :m
RETURNING hits""")


def limit(bucket: str, per_ip: bool = False):
    """per_ip: for unauthenticated routes, where a caller could dodge a per-token limit by varying the header.
    Behind a reverse proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips so this is the client's IP."""
    def dep(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
        key = f"ip:{request.client.host if request.client else ''}" if per_ip else authorization or ""
        n = db.execute(_HIT, {"b": bucket, "k": hash_token(key), "m": int(time.time() // 60)}).scalar_one()
        db.commit()  # count the hit even if the request later fails
        if n > LIMITS[bucket]:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"})
    return dep


def prune(db: Session):
    """Drop rows from past windows (called by the sweeper) so unknown tokens do not pile up."""
    db.execute(text("DELETE FROM rate_hits WHERE minute < :m"), {"m": int(time.time() // 60)})
    db.commit()
