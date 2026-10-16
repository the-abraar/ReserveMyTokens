"""Signed usage receipts. The worker signs what it reports with its own Ed25519 key, so a stored receipt shows which
worker claimed which numbers. It does NOT make the numbers true (judge.md blocker 2).
The format is duplicated in worker/src/reserve_my_tokens_worker/receipts.py; tests/test_receipts.py fails if they drift."""
import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def payload(job_id: int, worker_id: int, output: str, prompt_tokens: int, completion_tokens: int, eval_duration_ns: int) -> bytes:
    digest = hashlib.sha256(output.encode()).hexdigest()
    return f"rmt-receipt-v1|{job_id}|{worker_id}|{digest}|{prompt_tokens}|{completion_tokens}|{eval_duration_ns}".encode()


def valid_public_key(b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(b64, validate=True))
        return True
    except ValueError:  # bad base64 (binascii.Error is a ValueError) or wrong key length
        return False


def verify(public_key_b64: str, signature_b64: str | None, data: bytes) -> bool:
    if not signature_b64:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.b64decode(signature_b64, validate=True), data)
        return True
    except (ValueError, InvalidSignature):
        return False
