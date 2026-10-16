"""Worker credentials (coordinator token + receipt signing key) live in the OS keychain via `keyring`
(macOS Keychain, Windows Credential Locker, Secret Service on Linux). There are no provider API keys to store:
v1 accepts none (Boundary A)."""
import json

import keyring

SERVICE = "reserve-my-tokens-worker"


def _account(coordinator_url: str, worker_id: int) -> str:
    return f"{coordinator_url.rstrip('/')}#worker-{worker_id}"


def save(coordinator_url: str, worker_id: int, token: str, signing_key: str) -> None:
    keyring.set_password(SERVICE, _account(coordinator_url, worker_id), json.dumps({"token": token, "signing_key": signing_key}))


def load(coordinator_url: str, worker_id: int) -> dict | None:
    raw = keyring.get_password(SERVICE, _account(coordinator_url, worker_id))
    return json.loads(raw) if raw else None


def delete(coordinator_url: str, worker_id: int) -> bool:
    try:
        keyring.delete_password(SERVICE, _account(coordinator_url, worker_id))
        return True
    except keyring.errors.PasswordDeleteError:
        return False
