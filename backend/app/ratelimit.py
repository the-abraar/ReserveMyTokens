"""Per-token fixed-window rate limit, counted in the database so every API process shares one limit."""
import os
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import hash_token
from .database import get_db

LIMITS = {"submit": int(os.getenv("RATE_SUBMIT_PER_MIN", "30")), "lease": int(os.getenv("RATE_LEASE_PER_MIN", "120"))}

# Atomic upsert on Postgres and SQLite >= 3.35: a new minute resets the row's counter.
_HIT = text("""INSERT INTO rate_hits (bucket, key_hash, minute, hits) VALUES (:b, :k, :m, 1)
ON CONFLICT (bucket, key_hash) DO UPDATE
SET hits = CASE WHEN rate_hits.minute = :m THEN rate_hits.hits + 1 ELSE 1 END, minute = :m
RETURNING hits""")


def limit(bucket: str):
    def dep(authorization: str | None = Header(None), db: Session = Depends(get_db)):
        n = db.execute(_HIT, {"b": bucket, "k": hash_token(authorization or ""), "m": int(time.time() // 60)}).scalar_one()
        db.commit()  # count the hit even if the request later fails
        if n > LIMITS[bucket]:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"})
    return dep


def prune(db: Session):
    """Drop rows from past windows (called by the sweeper) so unknown tokens do not pile up."""
    db.execute(text("DELETE FROM rate_hits WHERE minute < :m"), {"m": int(time.time() // 60)})
    db.commit()
