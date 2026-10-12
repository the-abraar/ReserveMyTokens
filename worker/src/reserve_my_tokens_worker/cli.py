import logging
import os

import click

from .ollama_adapter import OllamaAdapter
from .polling_client import CoordinatorClient


@click.group()
def main():
    """ReserveMyTokens Worker CLI"""
    logging.basicConfig(level=logging.INFO)


@main.command()
@click.option('--coordinator-url', default='http://localhost:8000', help='URL of the coordinator')
@click.option('--worker-id', type=int, required=True, envvar='RMT_WORKER_ID')
@click.option('--poll-interval', default=5, help='Polling interval in seconds')
def start(coordinator_url, worker_id, poll_interval):
    """Start the worker. Token is read from RMT_WORKER_TOKEN (keychain storage is TODO)."""
    token = os.environ.get("RMT_WORKER_TOKEN") or click.prompt("Worker token", hide_input=True)
    ollama = OllamaAdapter()
    models = ollama.detect_models()
    click.echo(f"Serving Ollama models: {models}")
    CoordinatorClient(coordinator_url, worker_id, token, poll_interval).start_polling(ollama, models)


if __name__ == '__main__':
    main()
