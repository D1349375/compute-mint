"""The dashboard's demo data: synthetic sessions through the real gateway on a mock upstream."""
import json
import sqlite3

from demo.seed import forbidden_values, replay, seed

from compute_mint.labels import Label
from compute_mint.policy import Policy


def test_seed_covers_every_lane_masking_and_the_review_queue(tmp_path):
    result = seed(tmp_path)
    db = sqlite3.connect(tmp_path / "ledger.db")
    lanes = {lane: n for lane, n in db.execute("SELECT lane, COUNT(*) FROM requests GROUP BY lane")}
    assert set(lanes) == {"contributor", "standard", "local", "held"}
    assert db.execute("SELECT COUNT(*) FROM requests WHERE masked_spans > 0 AND lane = 'contributor'").fetchone()[0] >= 2
    # Only the comparison phase is paid; held and local rows exist only on credits.
    assert {b for (b,) in db.execute("SELECT DISTINCT billing FROM requests WHERE lane = 'standard'")} == {"paid"}
    assert {b for (b,) in db.execute("SELECT DISTINCT billing FROM requests WHERE lane IN ('held','local')")} == {"credits"}
    ts = [t for (t,) in db.execute("SELECT ts FROM requests ORDER BY id")]
    assert ts == sorted(ts) and ts[-1] - ts[0] > 3600

    payloads = [p for (p,) in db.execute("SELECT sent_payload FROM requests WHERE lane = 'contributor'")]
    assert all(p for p in payloads)
    text = "\n".join(payloads)
    assert "⟨API_KEY_1⟩" in text and "⟨EMAIL_1⟩" in text and "⟨TW_PHONE_1⟩" in text
    assert not [v for v in forbidden_values() if v in text]
    assert all(json.loads(p) for p in payloads)

    pending = {p["suggested_pattern"] for p in result["pending"]}
    assert {"/work/slugkit/docs/**", "/work/billflow/shared/**"} <= pending
    assert "/work/slugkit/slugkit/**" not in pending


def test_a_review_decision_moves_the_replayed_session_to_contributor(tmp_path):
    seed(tmp_path)
    assert {lane for _, lane in replay(tmp_path)} == {"contributor", "held"}

    policy = Policy(tmp_path / "policy.db")
    for item in policy.pending():
        if item["suggested_pattern"] in ("/work/slugkit/docs/**", "/work/billflow/shared/**"):
            policy.decide(item["id"], Label.PUBLIC)
    assert {lane for _, lane in replay(tmp_path)} == {"contributor"}
    assert {lane for _, lane in replay(tmp_path, local=True)} == {"contributor"}
