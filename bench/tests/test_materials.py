"""The synthetic repositories, their truth labels and canaries are consistent with each other."""
import importlib.util
import re

import pytest
from compute_mint.detect import find_spans
from compute_mint.labels import Label

from bench import BENCH_DIR
from bench.repos import load_repo, repo_names, solution_files
from bench.taskset import all_tasks

# Files the gateway's detectors flag although the owner labels them below FLOOR: the maintainer's
# public address (published on purpose) and a dummy phone number in a test. The gateway masks
# them anyway; this list documents the over-masking and fails if it changes unnoticed.
OVER_MASKED = {
    "slugkit": {"README.md", "CONTRIBUTING.md", "pyproject.toml"},
    "billflow": {"tests/test_redact.py"},
}

# Secret formats that scanners (GitHub push protection, ...) recognize. The synthetic values must
# not look like any of them, so the repository can become public without a blocked push.
KNOWN_SECRET_FORMATS = [r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"xox[abpr]-[A-Za-z0-9-]{10,}",
                        r"AIza[0-9A-Za-z_-]{35}", r"sk-ant-[A-Za-z0-9_-]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                        r"sk_live_[A-Za-z0-9]{10,}", r"pypi-AgEIcHlwaS5vcmc"]


def created_paths(repo: str) -> set[str]:
    out: set[str] = set()
    for it in all_tasks():
        if it.task.repo == repo:
            out |= set(solution_files(it.task.id))
    return out


@pytest.mark.parametrize("repo", repo_names())
def test_every_label_names_a_real_or_created_file(repo):
    r = load_repo(repo)
    known = set(r.files) | created_paths(repo)
    assert set(r.labels) <= known, sorted(set(r.labels) - known)


@pytest.mark.parametrize("repo", repo_names())
def test_stored_names_use_the_dot_prefix_convention(repo):
    """.env and .gitignore are committed as _dot_env / _dot_gitignore (the project .gitignore would skip them)."""
    base = BENCH_DIR / "materials" / repo / "files"
    offenders = [p for p in base.rglob("*") if any(part.startswith(".") for part in p.relative_to(base).parts)]
    assert offenders == []
    assert ".env" in load_repo(repo).files and load_repo(repo).label_of(".env") is Label.FLOOR


@pytest.mark.parametrize("repo", repo_names())
def test_every_canary_is_in_the_repo_and_only_in_files_labeled_at_least_as_strictly(repo):
    r = load_repo(repo)
    assert len({c.id for c in r.canaries}) == len(r.canaries)
    for c in r.canaries:
        where = [path for path, text in r.files.items() if c.value in text]
        assert where, f"canary {c.id} appears in no file"
        too_lax = [p for p in where if r.label_of(p) < c.label]
        assert not too_lax, f"canary {c.id} ({c.label.name}) sits in less strictly labeled files {too_lax}"


@pytest.mark.parametrize("repo", repo_names())
def test_every_sensitive_nonempty_file_holds_a_canary(repo):
    """A file the owner labels CONFIDENTIAL or FLOOR must carry something the canary scan can see."""
    r = load_repo(repo)
    for path, text in r.files.items():
        if r.label_of(path) >= Label.CONFIDENTIAL and text.strip():
            assert any(c.value in text and c.label >= Label.CONFIDENTIAL for c in r.canaries), path


@pytest.mark.parametrize("repo", repo_names())
def test_detector_spans_only_in_the_documented_files(repo):
    r = load_repo(repo)
    flagged = {p for p, text in r.files.items() if r.label_of(p) < Label.FLOOR and find_spans(text)}
    assert flagged == OVER_MASKED[repo]


@pytest.mark.parametrize("repo", repo_names())
def test_nothing_looks_like_a_scannable_real_secret(repo):
    r = load_repo(repo)
    texts = list(r.files.values()) + [t for it in all_tasks() for t in solution_files(it.task.id).values()]
    for pattern in KNOWN_SECRET_FORMATS:
        for text in texts:
            assert not re.search(pattern, text), pattern


@pytest.mark.parametrize("repo", repo_names())
def test_no_real_looking_phone_numbers_or_ids(repo):
    """Phone numbers are the 0900-000-xxx block, ids are TW5041xxxx: obviously synthetic."""
    r = load_repo(repo)
    for path, text in r.files.items():
        for m in re.finditer(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)", text):
            assert m.group(0).replace("-", "").startswith("0900000"), (path, m.group(0))


def test_bulk_files_are_reproducible_from_the_generator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gen_bulk", BENCH_DIR / "materials" / "gen_bulk.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    r = load_repo("billflow")
    assert gen.billrun_log() == r.files["logs/billrun-2026-10-21.log"]
    assert gen.slow_queries_log() == r.files["logs/slow-queries.log"]
    assert gen.sample_invoices_csv() == r.files["data/sample_invoices.csv"]
    assert gen.legacy_import_py() == r.files["legacy/legacy_import.py"]


def test_bulky_files_exceed_the_brokers_compaction_threshold():
    r = load_repo("billflow")
    big = [p for p, t in r.files.items() if len(t) > 4000]
    assert {"logs/billrun-2026-10-21.log", "legacy/legacy_import.py", "data/sample_invoices.csv"} <= set(big)
