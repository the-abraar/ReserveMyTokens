import requests

from .provider import ModelProvider


class OllamaAdapter(ModelProvider):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    def detect_models(self) -> list[str]:
        r = requests.get(f"{self.base_url}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def run_inference(self, model: str, prompt: str, max_tokens: int, temperature: float = 0) -> dict:
        r = requests.post(f"{self.base_url}/api/generate", timeout=600, json={
            "model": model, "prompt": prompt, "stream": False, "options": {"num_predict": max_tokens, "temperature": temperature}})
        r.raise_for_status()
        d = r.json()
        return {"output": d["response"], "prompt_tokens": d.get("prompt_eval_count", 0),
                "completion_tokens": d.get("eval_count", 0), "eval_duration_ns": d.get("eval_duration", 0)}
