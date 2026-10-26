"""Retry a flaky callable."""
import time


def retry(fn, attempts: int = 3, delay: float = 0.0, exceptions=(Exception,)):
    """Call ``fn()`` until it returns, trying at most ``attempts`` times in total.

    Only exceptions listed in ``exceptions`` are retried; the last one is re-raised when
    every attempt failed. ``delay`` seconds are slept between attempts.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except exceptions as exc:
            last = exc
            if delay:
                time.sleep(delay)
    raise last
