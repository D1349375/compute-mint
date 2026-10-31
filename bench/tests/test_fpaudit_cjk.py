from bench.fpaudit_cjk import audit


def test_cjk_fingerprints_catch_the_mentions_and_hold_back_no_public_text():
    r = audit(rows=500)
    assert all(r["mentions"].values()), r["mentions"]
    assert {name: lines for name, lines in r["flagged"].items() if lines} == {}
    assert r["terms"] > 500


def test_the_documented_limits_are_still_limits():
    # If one of these starts being caught, the README's list of misses is out of date.
    assert not any(audit(rows=0)["misses"].values())
