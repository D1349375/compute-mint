import json

from scripts.client_report import terms_summary


def test_counts_per_terms_in_the_register():
    assert terms_summary("config/clients.json") == {"net30": 1, "net45": 1, "net30eom": 1, "net60": 1, "eom": 1}


def test_counts_repeated_terms(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"clients": [{"terms": "net30"}, {"terms": "net30"}, {"terms": "eom"}]}), encoding="utf-8")
    assert terms_summary(str(path)) == {"net30": 2, "eom": 1}


def test_default_path_is_the_register():
    assert sum(terms_summary().values()) == 5
