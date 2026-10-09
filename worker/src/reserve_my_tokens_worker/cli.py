import click
from .polling_client import CoordinatorClient
from .ollama_adapter import OllamaAdapter

@click.group()
def main():
    """ReserveMyTokens Worker CLI"""
    pass

@main.command()
@click.option('--coordinator-url', default='http://localhost:8080', help='URL of the coordinator')
@click.option('--poll-interval', default=5, help='Polling interval in seconds')
def start(coordinator_url, poll_interval):
    """Start the worker node"""
    click.echo(f"Starting worker, connecting to {coordinator_url}")
    
    ollama = OllamaAdapter()
    models = ollama.detect_models()
    click.echo(f"Detected Ollama models: {models}")
    
    client = CoordinatorClient(coordinator_url, poll_interval)
    client.start_polling(ollama)

if __name__ == '__main__':
    main()
