from compute_mint.labels import Label

from bench.reviewer import API_NAMES, Reviewer, truth_paths
from bench.repos import load_repo
from bench.taskset import all_tasks


class FakeClient:
    """Just enough of the gateway's review API to drive the reviewer."""

    def __init__(self, pending):
        self.pending = [dict(p, id=i + 1) for i, p in enumerate(pending)]
        self.posted = []

    def get(self, url):
        client = self

        class R:
            def json(self):
                return {"pending": list(client.pending), "rules": []}
        return R()

    def post(self, url, json):
        item_id = int(url.rsplit("/", 1)[1])
        self.posted.append((item_id, json))
        self.pending = [p for p in self.pending if p["id"] != item_id]

        class R:
            def raise_for_status(self):
                pass
        return R()


TRUTH = {
    "/w/a/src/x.py": Label.OWN_IP, "/w/a/src/y.py": Label.OWN_IP,
    "/w/a/docs/public.md": Label.PUBLIC, "/w/a/docs/secret.md": Label.CONFIDENTIAL,
    "/w/a/config/people.json": Label.FLOOR, "/w/a/.env": Label.FLOOR,
}


def test_floor_is_answered_with_confidential_because_the_api_has_no_floor():
    assert API_NAMES[Label.FLOOR] == "confidential"


def test_homogeneous_directory_gets_the_suggested_pattern_and_mixed_directory_the_exact_path():
    client = FakeClient([
        {"path": "/w/a/src/x.py", "suggested_pattern": "/w/a/src/**"},
        {"path": "/w/a/docs/public.md", "suggested_pattern": "/w/a/docs/**"},
        {"path": "/w/a/config/people.json", "suggested_pattern": "/w/a/config/**"},
    ])
    rev = Reviewer(TRUTH, budget=10)
    assert rev.review(client, "t") == 3
    posted = {i: j for i, j in client.posted}
    assert posted[1] == {"label": "own_ip", "pattern": "/w/a/src/**"}
    assert posted[2] == {"label": "public", "pattern": "/w/a/docs/public.md"}   # secret.md lives next to it
    assert posted[3] == {"label": "confidential", "pattern": "/w/a/config/**"}


def test_credential_files_do_not_block_a_directory_rule():
    truth = {"/w/a/cfg/app.json": Label.PUBLIC, "/w/a/cfg/.env": Label.FLOOR}
    client = FakeClient([{"path": "/w/a/cfg/app.json", "suggested_pattern": "/w/a/cfg/**"}])
    Reviewer(truth, budget=1).review(client)
    assert client.posted[0][1]["pattern"] == "/w/a/cfg/**"   # .env is FLOOR through the gateway's own rule


def test_budget_limits_decisions_per_call():
    client = FakeClient([{"path": f"/w/a/src/f{i}.py", "suggested_pattern": f"/w/a/src/f{i}.py"} for i in range(5)])
    rev = Reviewer({f"/w/a/src/f{i}.py": Label.OWN_IP for i in range(5)}, budget=2)
    assert rev.review(client) == 2 and len(client.pending) == 3


def test_error_rate_one_answers_public_whatever_the_truth():
    client = FakeClient([{"path": "/w/a/docs/secret.md", "suggested_pattern": "/w/a/docs/**"}])
    Reviewer(TRUTH, budget=1, error_rate=1.0).review(client)
    assert client.posted[0][1]["label"] == "public"


def test_truth_paths_cover_existing_and_created_files_with_absolute_mounted_paths():
    repos = {n: load_repo(n) for n in ("slugkit", "billflow")}
    ids = {n: [it.task.id for it in all_tasks() if it.task.repo == n] for n in repos}
    truth = truth_paths(repos, ids)
    assert truth["/work/billflow/.env"] is Label.FLOOR
    assert truth["/work/slugkit/slugkit/textutil.py"] is Label.PUBLIC   # created by a solution
    assert truth["/work/billflow/scripts/client_report.py"] is Label.OWN_IP
    assert truth["/work/slugkit/docs/internal/release-notes-draft.md"] is Label.OWN_IP
