"""Unit tests for the pure login rate-limiter logic.

The clock is injected (the ``now`` param) so window expiry is tested without
sleeping. Routes are out of scope here — this locks the limiter's behaviour.
"""

from app.core.rate_limit import LoginRateLimiter


def test_allows_attempts_below_limit() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(2):
        assert limiter.is_blocked("1.2.3.4", now=0.0) is False
        limiter.record_failure("1.2.3.4", now=0.0)

    assert limiter.is_blocked("1.2.3.4", now=0.0) is False


def test_blocks_once_limit_reached() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(3):
        limiter.record_failure("1.2.3.4", now=0.0)

    assert limiter.is_blocked("1.2.3.4", now=0.0) is True


def test_window_expiry_resets_counter() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(3):
        limiter.record_failure("1.2.3.4", now=0.0)
    assert limiter.is_blocked("1.2.3.4", now=0.0) is True

    # Once the window has fully elapsed, the key is free again.
    assert limiter.is_blocked("1.2.3.4", now=60.0) is False


def test_reset_clears_counter() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(3):
        limiter.record_failure("1.2.3.4", now=0.0)
    assert limiter.is_blocked("1.2.3.4", now=0.0) is True

    limiter.reset("1.2.3.4")
    assert limiter.is_blocked("1.2.3.4", now=0.0) is False


def test_keys_are_independent() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)

    for _ in range(3):
        limiter.record_failure("1.2.3.4", now=0.0)

    assert limiter.is_blocked("1.2.3.4", now=0.0) is True
    assert limiter.is_blocked("5.6.7.8", now=0.0) is False
