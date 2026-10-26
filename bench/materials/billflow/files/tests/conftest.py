import pytest

from fixtures.customers import CLIENTS


@pytest.fixture
def clients():
    return [dict(c) for c in CLIENTS]
