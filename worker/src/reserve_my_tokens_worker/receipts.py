"""Signs usage receipts with the worker's Ed25519 key. Same format as backend/app/receipts.py (a test checks both)."""
import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def payload(job_id: int, worker_id: int, output: str, prompt_tokens: int, completion_tokens: int, eval_duration_ns: int) -> bytes:
    digest = hashlib.sha256(output.encode()).hexdigest()
    return f"rmt-receipt-v1|{job_id}|{worker_id}|{digest}|{prompt_tokens}|{completion_tokens}|{eval_duration_ns}".encode()


def new_key() -> str:
    """A fresh private key as base64 raw bytes (stored in the OS keychain, never sent anywhere)."""
    raw = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                     serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def public_key(private_b64: str) -> str:
    pub = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64)).public_key()
    return base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def sign(private_b64: str, job_id: int, worker_id: int, result: dict) -> str:
    data = payload(job_id, worker_id, result["output"], result["prompt_tokens"], result["completion_tokens"],
                   result["eval_duration_ns"])
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64)).sign(data)).decode()
