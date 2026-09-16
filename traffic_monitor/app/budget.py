"""
Rolling 30-day API usage guard (ROADMAP.md section 2). This is a safety
property, not an optimization: the user handed us a key, and we don't get
to spend it past their free tier without their say-so.

At 80% usage: warn (caller surfaces this via the diagnostic sensor and
logs). At 100%: stop -- allow() returns False and callers must not make
the request.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("traffic_monitor.budget")

ROLLING_WINDOW_SECONDS = 30 * 24 * 3600


@dataclass
class BudgetGuard:
    path: Path
    monthly_limit: int = 20_000
    warn_threshold: float = 0.8
    _timestamps: list[float] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            self._timestamps = list(data.get("timestamps", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read usage data at %s: %s", self.path, exc)
            self._timestamps = []
        self._prune()

    def _prune(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        cutoff = now - ROLLING_WINDOW_SECONDS
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"timestamps": self._timestamps}))

    def used(self, now: float | None = None) -> int:
        self._prune(now)
        return len(self._timestamps)

    def remaining(self, now: float | None = None) -> int:
        return max(0, self.monthly_limit - self.used(now))

    def usage_ratio(self, now: float | None = None) -> float:
        if self.monthly_limit <= 0:
            return 1.0
        return self.used(now) / self.monthly_limit

    def is_warning(self, now: float | None = None) -> bool:
        return self.usage_ratio(now) >= self.warn_threshold

    def is_exhausted(self, now: float | None = None) -> bool:
        return self.used(now) >= self.monthly_limit

    def allow(self, now: float | None = None) -> bool:
        """True if a request can be made without exceeding the monthly budget."""
        return not self.is_exhausted(now)

    def record(self, count: int = 1, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._timestamps.extend([now] * count)
        self._save()
        if self.is_exhausted(now):
            logger.error("TomTom API monthly budget exhausted (%d/%d)", self.used(now), self.monthly_limit)
        elif self.is_warning(now):
            logger.warning(
                "TomTom API usage at %.0f%% of monthly budget (%d/%d)",
                self.usage_ratio(now) * 100,
                self.used(now),
                self.monthly_limit,
            )
