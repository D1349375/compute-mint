"""Meta Model API list prices, USD per 1M tokens (dev.meta.ai/docs/pricing-rate-limits, checked 2026-10-26)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    cached_input: float
    output: float


PRICES: dict[str, Price] = {
    "muse-spark-1.3": Price(1.25, 0.15, 4.25),
    "muse-spark-1.2": Price(1.25, 0.15, 4.25),
    "muse-spark-1.1": Price(1.25, 0.15, 4.25),
    "muse-spark-1.3-contributor": Price(0.10, 0.002, 0.20),
    "muse-spark-1.2-contributor": Price(0.10, 0.002, 0.20),
    "muse-wonder-1.0": Price(4.00, 0.20, 20.00),
}

# The Standard model a Contributor model stands in for: the counterfactual price.
STANDARD_OF = {
    "muse-spark-1.3-contributor": "muse-spark-1.3",
    "muse-spark-1.2-contributor": "muse-spark-1.2",
}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int

    @classmethod
    def from_openai(cls, usage: dict | None) -> "Usage":
        usage = usage or {}
        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") or usage.get("cached_tokens") or 0
        return cls(int(usage.get("prompt_tokens") or 0), int(cached), int(usage.get("completion_tokens") or 0))


def cost(model: str, u: Usage) -> float:
    p = PRICES[model]
    uncached = max(u.prompt_tokens - u.cached_tokens, 0)
    return (uncached * p.input + u.cached_tokens * p.cached_input + u.completion_tokens * p.output) / 1e6


def counterfactual_cost(model: str, u: Usage) -> float:
    """What the same tokens would have cost on the Standard tier."""
    return cost(STANDARD_OF.get(model, model), u)
