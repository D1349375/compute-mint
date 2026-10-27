import tempfile
from pathlib import Path

import pytest

from bench.repos import load_repo, write_tree


@pytest.fixture
def workspace_factory():
    """Fresh copies of a synthetic repository in temp directories."""
    dirs = []

    def make(repo: str) -> Path:
        d = tempfile.TemporaryDirectory(prefix="bench-test-")
        dirs.append(d)
        root = Path(d.name)
        write_tree(load_repo(repo).files, root)
        return root

    yield make
    for d in dirs:
        d.cleanup()
