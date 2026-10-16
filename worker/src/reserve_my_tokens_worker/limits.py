"""Local limits the contributor sets: compute time and generated tokens per rolling 24 h, and a kill switch file.
shortcut: usage counters live in memory and reset when the worker restarts; persist them if a daily cap must
survive restarts."""
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

DAY = 86400.0


@dataclass
class Limits:
    max_compute_seconds: float | None = None  # wall time spent in inference per rolling 24 h
    max_tokens: int | None = None  # completion tokens generated per rolling 24 h
    kill_file: Path | None = None  # stop serving as soon as this file exists
    _log: deque = field(default_factory=deque)  # (finished_at, seconds, tokens)

    def killed(self) -> bool:
        return bool(self.kill_file and self.kill_file.exists())

    def _used(self, now: float) -> tuple[float, int]:
        while self._log and self._log[0][0] < now - DAY:
            self._log.popleft()
        return sum(s for _, s, _ in self._log), sum(t for _, _, t in self._log)

    def remaining_tokens(self, now: float | None = None) -> int | None:
        """None = no token cap. The lease asks only for jobs whose max_tokens fit this."""
        return None if self.max_tokens is None else max(0, self.max_tokens - self._used(now or time.time())[1])

    def exhausted(self, now: float | None = None) -> bool:
        secs, _ = self._used(now or time.time())
        return (self.max_compute_seconds is not None and secs >= self.max_compute_seconds) or self.remaining_tokens(now) == 0

    def record(self, seconds: float, tokens: int, now: float | None = None) -> None:
        self._log.append((now or time.time(), seconds, tokens))
