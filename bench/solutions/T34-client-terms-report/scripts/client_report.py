"""Small reports over the client register."""
from collections import Counter

from billflow.clients import load_clients


def terms_summary(path: str = "config/clients.json") -> dict[str, int]:
    """Number of clients per payment-terms string, e.g. ``{"net30": 2, "eom": 1}``."""
    return dict(Counter(client["terms"] for client in load_clients(path)))


if __name__ == "__main__":
    for terms, count in sorted(terms_summary().items()):
        print(f"{terms}: {count}")
