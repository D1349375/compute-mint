import pytest

from slugkit.retry import retry


class Flaky:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("boom")
        return "ok"


def test_returns_on_first_success():
    fn = Flaky(0)
    assert retry(fn) == "ok"
    assert fn.calls == 1


def test_succeeds_on_the_last_allowed_attempt():
    fn = Flaky(2)
    assert retry(fn, attempts=3) == "ok"
    assert fn.calls == 3


def test_gives_up_after_exactly_attempts_calls():
    fn = Flaky(10)
    with pytest.raises(RuntimeError):
        retry(fn, attempts=3)
    assert fn.calls == 3
