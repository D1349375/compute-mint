import json

from billflow.clients import find_client, load_clients


def test_exact_match(clients):
    assert find_client(clients, clients[0]["name"])["id"] == clients[0]["id"]


def test_match_ignores_case_and_surrounding_space(clients):
    wanted = clients[1]
    found = find_client(clients, "  " + wanted["name"].upper() + " ")
    assert found is not None and found["id"] == wanted["id"]


def test_unknown_name_returns_none(clients):
    assert find_client(clients, "Nobody Ltd.") is None


def test_load_clients(tmp_path):
    path = tmp_path / "clients.json"
    path.write_text(json.dumps({"clients": [{"id": "x", "name": "X"}]}), encoding="utf-8")
    assert load_clients(path) == [{"id": "x", "name": "X"}]
