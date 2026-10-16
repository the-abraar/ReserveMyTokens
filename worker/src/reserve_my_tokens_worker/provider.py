"""The adapter contract between the worker and a local inference backend.

v1 supply is donor-run local open-weight models only (docs/provider-terms.md), so an adapter takes no API key and
reports no provider cost. Pricing is server-side (coordinator `GET /estimate`), never the worker's claim, and usage is
the backend's own self-reported metering (`usage_source`)."""
from abc import ABC, abstractmethod

# Keys of run_inference's result: the coordinator's `Result` body minus `signature` (backend/tests/test_receipts.py checks).
RESULT_KEYS = frozenset({"output", "prompt_tokens", "completion_tokens", "eval_duration_ns"})


class ModelProvider(ABC):
    name: str
    usage_source = "self_reported"  # nothing outside the donor's machine measured these numbers

    @abstractmethod
    def detect_models(self) -> list[str]:
        """Model names this backend can serve right now."""

    @abstractmethod
    def run_inference(self, model: str, prompt: str, max_tokens: int, temperature: float = 0) -> dict:
        """Run one completion. Returns a dict with exactly RESULT_KEYS."""
