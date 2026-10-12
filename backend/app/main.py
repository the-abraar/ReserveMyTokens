import asyncio
import contextlib
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import jobs, users, workers


async def _sweep(interval: float):
    from .database import SessionLocal
    from .models.ledger import now

    def once():
        with SessionLocal() as db:
            workers.reap_expired(db, now())
    while True:
        try:
            await asyncio.to_thread(once)
        except Exception:  # keep sweeping; a transient DB error must not kill the task
            logging.getLogger(__name__).exception("sweeper pass failed")
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def lifespan(_):
    task = asyncio.create_task(_sweep(float(os.getenv("SWEEP_INTERVAL_SECONDS", "30"))))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# Schema is managed by Alembic (`alembic upgrade head`), not create_all.
app = FastAPI(title="ReserveMyTokens API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(users.router)
app.include_router(workers.router)
app.include_router(jobs.router)


@app.get("/")
def read_root():
    return {"message": "ReserveMyTokens API (test credits only)"}
