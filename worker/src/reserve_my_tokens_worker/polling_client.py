import logging
import time

import requests

from . import receipts
from .limits import Limits

logger = logging.getLogger(__name__)  # never log prompts or outputs (judge.md blocker 7)

# Boundary D: the only work a worker accepts is one inference call with these fields. Anything else is refused.
JOB_FIELDS = {"job_id": int, "model": str, "prompt": str, "max_tokens": int}
OPTIONAL_FIELDS = {"temperature": (int, float), "lease_expires_at": str}


def parse_job(job: dict, models: list[str]) -> dict:
    """Validated inference job, or ValueError. Unknown fields, wrong types or a model we did not offer are refused,
    so a coordinator (or anyone holding its keys) cannot make the worker do anything except run an offered model."""
    extra = set(job) - set(JOB_FIELDS) - set(OPTIONAL_FIELDS)
    if extra:
        raise ValueError(f"unexpected fields {sorted(extra)}")
    for k, t in {**JOB_FIELDS, **OPTIONAL_FIELDS}.items():
        if (k in JOB_FIELDS or k in job) and (not isinstance(job.get(k), t) or isinstance(job.get(k), bool)):
            raise ValueError(f"bad field {k}")
    if job["model"] not in models:
        raise ValueError("model not offered by this worker")
    if not 1 <= job["max_tokens"] <= 4096 or not 0 <= job.get("temperature", 0) <= 2:
        raise ValueError("limits out of range")
    return job


class CoordinatorClient:
    def __init__(self, coordinator_url: str, worker_id: int, token: str, poll_interval: float = 5,
                 signing_key: str | None = None, wait: float = 20, limits: Limits | None = None):
        self.url = coordinator_url.rstrip("/")
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self.wait = wait  # long-poll seconds the coordinator holds the request open (0 = short poll)
        self.signing_key = signing_key
        self.limits = limits or Limits()
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def lease(self, models: list[str], max_tokens: int | None = None):
        body = {"models": models, **({"max_tokens": min(max_tokens, 4096)} if max_tokens else {})}
        r = self.s.post(f"{self.url}/workers/{self.worker_id}/lease", params={"wait": self.wait}, json=body,
                        timeout=self.wait + 30)
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def register_key(self, public_key: str):
        r = self.s.put(f"{self.url}/workers/{self.worker_id}/public_key", json={"public_key": public_key}, timeout=30)
        r.raise_for_status()

    def submit_result(self, job_id: int, result: dict):
        body = dict(result)
        if self.signing_key:
            body["signature"] = receipts.sign(self.signing_key, job_id, self.worker_id, result)
        r = self.s.post(f"{self.url}/jobs/{job_id}/result", json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _serve_one(self, provider, models: list[str]) -> bool:
        """One lease-and-run pass. True if a job was leased (run or refused)."""
        if self.limits.exhausted():
            logger.info("local limit reached; pausing")
            time.sleep(self.poll_interval)
            return False
        job = self.lease(models, self.limits.remaining_tokens())
        if not job:
            if not self.wait:
                time.sleep(self.poll_interval)
            return False
        if self.limits.killed():  # switched off while we waited: let the lease expire so the job is requeued
            return True
        try:
            job = parse_job(job, models)
        except ValueError as e:
            logger.warning("refused job %s: %s", job.get("job_id"), e)
            return True
        logger.info("leased job %s", job["job_id"])
        t0 = time.monotonic()
        res = provider.run_inference(job["model"], job["prompt"], job["max_tokens"], job.get("temperature", 0))
        self.limits.record(time.monotonic() - t0, res["completion_tokens"])
        self.submit_result(job["job_id"], res)
        logger.info("submitted job %s (%s tokens)", job["job_id"], res["completion_tokens"])
        return True

    def start_polling(self, provider, models: list[str]):
        try:
            while not self.limits.killed():
                try:
                    self._serve_one(provider, models)
                except requests.RequestException as e:
                    logger.warning("request failed: %s", type(e).__name__)
                    time.sleep(self.poll_interval)
            logger.info("kill switch set; stopping")
        except KeyboardInterrupt:
            logger.info("stopping")
