"""
Tests for src/bhai/resilience/retry.py — retry with exponential backoff.
"""

from unittest.mock import MagicMock, patch

import pytest

from bhai.resilience.retry import retry_with_backoff


def test_success_on_first_try():
    """Function that always succeeds is called exactly once."""
    fn = MagicMock(return_value="ok")
    result = retry_with_backoff(fn, max_attempts=3)
    assert result == "ok"
    assert fn.call_count == 1


def test_success_after_two_failures():
    """Function that fails twice then succeeds is retried correctly."""
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient error")
        return "recovered"

    with patch("bhai.resilience.retry.time.sleep"):  # skip actual delays
        result = retry_with_backoff(flaky, max_attempts=3, base_delay=0.01)

    assert result == "recovered"
    assert call_count == 3


def test_raises_after_max_attempts():
    """After max_attempts, the last exception is re-raised."""
    fn = MagicMock(side_effect=ValueError("permanent failure"))

    with patch("bhai.resilience.retry.time.sleep"):
        with pytest.raises(ValueError, match="permanent failure"):
            retry_with_backoff(fn, max_attempts=3)

    assert fn.call_count == 3


def test_on_failure_callback_called_each_attempt():
    """on_failure is called for each failed attempt with (exc, attempt_number)."""
    failures = []
    fn = MagicMock(side_effect=RuntimeError("oops"))

    with patch("bhai.resilience.retry.time.sleep"):
        with pytest.raises(RuntimeError):
            retry_with_backoff(
                fn,
                max_attempts=3,
                on_failure=lambda exc, attempt: failures.append((str(exc), attempt)),
            )

    assert len(failures) == 3
    assert failures[0] == ("oops", 1)
    assert failures[1] == ("oops", 2)
    assert failures[2] == ("oops", 3)


def test_exponential_backoff_delays():
    """Retry delays follow min(base * 2^(attempt-1), max_delay) pattern."""
    fn = MagicMock(side_effect=OSError("fail"))
    sleep_calls = []

    with patch(
        "bhai.resilience.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)
    ):
        with pytest.raises(OSError):
            retry_with_backoff(fn, max_attempts=4, base_delay=1.0, max_delay=5.0)

    # Attempt 1 fails → sleep 1.0
    # Attempt 2 fails → sleep 2.0
    # Attempt 3 fails → sleep 4.0 (would be 4.0, capped at 5.0)
    # Attempt 4 fails → no sleep (last attempt, raises immediately)
    assert len(sleep_calls) == 3
    assert sleep_calls[0] == 1.0
    assert sleep_calls[1] == 2.0
    assert sleep_calls[2] == 4.0


def test_max_delay_cap():
    """Backoff delay is capped at max_delay."""
    fn = MagicMock(side_effect=OSError("fail"))
    sleep_calls = []

    with patch(
        "bhai.resilience.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)
    ):
        with pytest.raises(OSError):
            retry_with_backoff(fn, max_attempts=5, base_delay=2.0, max_delay=3.0)

    # Delays: 2.0, 4.0 → capped to 3.0, 8.0 → capped to 3.0, 16.0 → capped to 3.0
    assert all(d <= 3.0 for d in sleep_calls)
    assert sleep_calls[0] == 2.0
    assert sleep_calls[1] == 3.0
