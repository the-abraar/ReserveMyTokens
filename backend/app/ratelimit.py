"""Per-token fixed-window rate limit. shortcut: in-memory, so it is per PROCESS (N workers = N x the limit,
resets on restart, entries for unknown tokens are never evicted); move to Redis before running >1 process."""
import os
import time

from fastapi import Header, HTTPException

from .auth import hash_token

LIMITS = {"submit": int(os.getenv("RATE_SUBMIT_PER_MIN", "30")), "lease": int(os.getenv("RATE_LEASE_PER_MIN", "120"))}
_hits: dict[tuple, tuple[int, int]] = {}  # (bucket, token_hash) -> (window_minute, count)


def limit(bucket: str):
    def dep(authorization: str | None = Header(None)):
        key, minute = (bucket, hash_token(authorization or "")), int(time.time() // 60)
        w, n = _hits.get(key, (minute, 0))
        n = n + 1 if w == minute else 1
        _hits[key] = (minute, n)
        if n > LIMITS[bucket]:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"})
    return dep
