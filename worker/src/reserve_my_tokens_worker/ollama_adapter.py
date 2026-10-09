import logging

logger = logging.getLogger(__name__)

class OllamaAdapter:
    def __init__(self):
        self.base_url = "http://localhost:11434"

    def detect_models(self):
        """Mock detection of local Ollama models."""
        # In reality, this would query http://localhost:11434/api/tags
        logger.info(f"Detecting models at {self.base_url}")
        return ["llama2", "mistral"]

    def run_inference(self, model: str, prompt: str):
        """Mock running inference via Ollama."""
        # In reality, this would post to http://localhost:11434/api/generate
        logger.info(f"Running inference on model '{model}' with prompt: '{prompt}'")
        return f"Mock response from {model} for prompt: '{prompt}'"
