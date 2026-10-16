import logging
import os
from pathlib import Path

import click
import requests

from . import credentials, receipts
from .limits import Limits
from .ollama_adapter import OllamaAdapter
from .polling_client import CoordinatorClient

DEFAULT_KILL_FILE = Path(click.get_app_dir("rmt-worker")) / "STOP"
url_opt = click.option("--coordinator-url", default="http://localhost:8000", envvar="RMT_COORDINATOR_URL", show_default=True)
id_opt = click.option("--worker-id", type=int, required=True, envvar="RMT_WORKER_ID")
kill_opt = click.option("--kill-file", type=click.Path(path_type=Path), default=DEFAULT_KILL_FILE, show_default=True,
                        help="Kill switch: the worker stops as soon as this file exists.")


@click.group()
def main():
    """ReserveMyTokens worker: serves local Ollama models to the coordinator. Inference only; no provider API keys."""
    logging.basicConfig(level=logging.INFO)


@main.command()
@url_opt
@id_opt
def login(coordinator_url, worker_id):
    """Store the worker token in the OS keychain and register a new receipt-signing key with the coordinator."""
    token = click.prompt("Worker token (from the dashboard)", hide_input=True)
    key = receipts.new_key()
    try:
        CoordinatorClient(coordinator_url, worker_id, token).register_key(receipts.public_key(key))
    except requests.HTTPError as e:
        hint = " (this worker already has a signing key: register a new worker)" if e.response.status_code == 409 else ""
        raise click.ClickException(f"coordinator refused the key: HTTP {e.response.status_code}{hint}")
    credentials.save(coordinator_url, worker_id, token, key)
    click.echo(f"Saved worker {worker_id} credentials to the OS keychain.")


@main.command()
@url_opt
@id_opt
def logout(coordinator_url, worker_id):
    """Delete this worker's credentials from the OS keychain."""
    click.echo("Deleted." if credentials.delete(coordinator_url, worker_id) else "Nothing stored.")


@main.command()
@url_opt
@id_opt
@click.option("--ollama-url", default="http://localhost:11434", envvar="RMT_OLLAMA_URL", show_default=True)
@click.option("--model", "allowed", multiple=True, help="Serve only these models (repeatable). Default: all detected.")
@click.option("--wait", default=20.0, show_default=True, help="Long-poll seconds per lease request (0 = short poll).")
@click.option("--poll-interval", default=5.0, show_default=True, help="Back-off seconds after an error or empty short poll.")
@click.option("--max-compute-hours", type=float, help="Inference wall time allowed per rolling 24 h.")
@click.option("--max-tokens-per-day", type=int, help="Completion tokens allowed per rolling 24 h.")
@kill_opt
def start(coordinator_url, worker_id, ollama_url, allowed, wait, poll_interval, max_compute_hours, max_tokens_per_day, kill_file):
    """Serve jobs until Ctrl-C or the kill switch. Credentials come from the keychain (`login`); RMT_WORKER_TOKEN is
    a fallback that sends unsigned receipts."""
    creds = credentials.load(coordinator_url, worker_id)
    if not creds:
        if not os.environ.get("RMT_WORKER_TOKEN"):
            raise click.ClickException("no stored credentials: run `rmt-worker login` first")
        click.echo("Using RMT_WORKER_TOKEN: receipts will be unsigned.", err=True)
        creds = {"token": os.environ["RMT_WORKER_TOKEN"], "signing_key": None}
    kill_file.unlink(missing_ok=True)  # starting is the explicit opposite of `stop`
    ollama = OllamaAdapter(ollama_url)
    models = [m for m in ollama.detect_models() if not allowed or m in allowed]
    if not models:
        raise click.ClickException("no allowed Ollama models found")
    click.echo(f"Serving Ollama models: {models}")
    limits = Limits(max_compute_seconds=max_compute_hours * 3600 if max_compute_hours else None,
                    max_tokens=max_tokens_per_day, kill_file=kill_file)
    CoordinatorClient(coordinator_url, worker_id, creds["token"], poll_interval, creds["signing_key"], wait, limits) \
        .start_polling(ollama, models)


@main.command()
@kill_opt
def stop(kill_file):
    """Kill switch: tell a running worker to stop taking jobs."""
    kill_file.parent.mkdir(parents=True, exist_ok=True)
    kill_file.touch()
    click.echo(f"Kill switch set ({kill_file}).")


if __name__ == "__main__":
    main()
