"""The client register (config/clients.json)."""
import json
from pathlib import Path


def load_clients(path: str | Path = "config/clients.json") -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["clients"]


def find_client(clients: list[dict], name: str) -> dict | None:
    """Look a client up by name, ignoring case and surrounding whitespace."""
    for client in clients:
        if client["name"] == name:
            return client
    return None
