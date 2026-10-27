"""Volume and negotiated discounts. The rate tables live in config/rates.json."""
import json
from decimal import Decimal
from pathlib import Path


def load_rates(path: str | Path = "config/rates.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def volume_discount(volume: Decimal, tiers: list[dict]) -> Decimal:
    """Rate of the highest tier whose ``min`` the monthly ``volume`` has reached."""
    rate = Decimal("0")
    for tier in sorted(tiers, key=lambda t: t["min"]):
        if volume >= Decimal(str(tier["min"])):
            rate = Decimal(str(tier["rate"]))
    return rate


def client_discount(client_id: str, volume: Decimal, rates: dict) -> Decimal:
    """Volume discount plus the client's negotiated extra, capped at ``rates["max_total"]``."""
    base = volume_discount(volume, rates["tiers"])
    extra = Decimal(str(rates.get("clients", {}).get(client_id, {}).get("extra", 0)))
    return min(base + extra, Decimal(str(rates.get("max_total", 1))))
