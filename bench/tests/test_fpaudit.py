"""The static false-positive audit of the fingerprints (bench/fpaudit.py)."""
import pytest

from bench import fpaudit
from bench.repos import load_repo
from bench.tools import mount_for


@pytest.fixture(scope="module")
def leak_outputs():
    import tempfile
    from pathlib import Path

    from bench.repos import write_tree
    from bench.tools import Workspace
    repo = load_repo("billflow")
    out = {}
    with tempfile.TemporaryDirectory(prefix="bench-audit-test-") as tmp:
        write_tree(repo.files, Path(tmp))
        ws = Workspace(Path(tmp), mount_for("billflow"))
        for rel in fpaudit.LEAK_TARGETS + ("tests/test_money.py", "tests/test_invoice.py"):
            out[("billflow", rel)] = ws.run_tests(rel)
    return out


def test_the_three_leaking_outputs_are_caught_and_ordinary_failures_are_not(leak_outputs):
    rows = fpaudit.audit(thresholds=(2,), outputs=leak_outputs)[2]
    assert rows["leak_outputs_caught"] == 3
    assert sorted(rows["flagged_outputs"]) == sorted(("billflow", t) for t in fpaudit.LEAK_TARGETS)


def test_no_public_file_is_held_back_at_the_default_threshold(leak_outputs):
    rows = fpaudit.audit(thresholds=(2,), outputs=leak_outputs)[2]
    assert rows["flagged_public_files"] == []
    assert len(rows["flagged_own_ip_files"]) <= 6      # the owner's company name sits in a confidential contract too


def test_a_higher_threshold_never_holds_back_more(leak_outputs):
    rows = fpaudit.audit(thresholds=(1, 2, 3, 4), outputs=leak_outputs)
    counts = [len(rows[t]["flagged_public_files"]) + len(rows[t]["flagged_own_ip_files"]) for t in (1, 2, 3, 4)]
    assert counts == sorted(counts, reverse=True)
