"""In-memory fixed-window rate limiter for login brute-force protection.

Pure logic — no FastAPI, no HTTP. State lives in a process-local dict keyed by
client IP, so it resets on reload and is not shared across instances (fine for
this single-instance local service). The clock is injectable so the window
expiry is testable without sleeping.

Fixed-window per key: ``(count, window_start)``. Cheaper and bounded in memory
compared to keeping a sliding list of timestamps, which is enough for a login
lockout.
"""

import time


class LoginRateLimiter:
    """Counts failed attempts per key within a fixed time window."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: dict[str, tuple[int, float]] = {}

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        """True if ``key`` has reached the failed-attempt limit in the window."""
        now = time.monotonic() if now is None else now
        entry = self._attempts.get(key)
        if entry is None:
            return False
        count, window_start = entry
        if now - window_start >= self._window_seconds:
            return False
        return count >= self._max_attempts

    def record_failure(self, key: str, now: float | None = None) -> None:
        """Register a failed attempt for ``key``, opening a window if needed."""
        now = time.monotonic() if now is None else now
        entry = self._attempts.get(key)
        if entry is None or now - entry[1] >= self._window_seconds:
            self._attempts[key] = (1, now)
        else:
            self._attempts[key] = (entry[0] + 1, entry[1])

    def reset(self, key: str) -> None:
        """Clear a key's counter, e.g. after a successful login."""
        self._attempts.pop(key, None)
