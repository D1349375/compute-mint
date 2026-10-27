"""Types and constants shared by the arms. No gateway, HTTP or upstream imports on purpose: the
naive arm (bench/naive.py) imports from here and must stay unable to send anything."""
from dataclasses import dataclass, field

from compute_mint.labels import Label

CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
STANDARD_MODEL = "muse-spark-1.3"
DIALS = {"public": Label.PUBLIC, "own_ip": Label.OWN_IP}


@dataclass(frozen=True)
class ArmSpec:
    name: str
    title: str
    executed: bool = True          # False: analysed from recorded histories, never sent anywhere
    all_standard: bool = False
    broker: bool = False
    learning: str = "none"         # none | reviewer | oracle
    strict_tools: bool = False     # what-if: distrust tool output that names no file (bench/shims.py)
    extra: bool = False            # not part of `--arms all`


ARM_SPECS = {
    "standard": ArmSpec("standard", "1. All Standard (no Mint)", all_standard=True),
    "naive": ArmSpec("naive", "2. Naive mid-session switch (simulated only)", executed=False),
    "mint": ArmSpec("mint", "3. Compute Mint (lanes + masking + origin)"),
    "mint_broker": ArmSpec("mint_broker", "4. Compute Mint + Context Broker", broker=True),
    "mint_learn": ArmSpec("mint_learn", "5. Mint + Broker + rule learning", broker=True, learning="reviewer"),
    "oracle": ArmSpec("oracle", "6. Mint + Broker + oracle rules (ceiling, extra)", broker=True, learning="oracle", extra=True),
    "mint_strict": ArmSpec("mint_strict", "7. Arm 5 + distrust tool output without a file (what-if, extra)", broker=True,
                           learning="reviewer", strict_tools=True, extra=True),
}
ALL_ARMS = [n for n, s in ARM_SPECS.items() if not s.extra]


@dataclass
class RunOptions:
    upstream: str = "mock"
    cache_block_tokens: int = 64
    reviews_per_task: int = 2
    reviewer_error_rate: float = 0.0
    seed: int = 1
    naive_switch: str = "mid"


@dataclass
class ArmRun:
    spec: ArmSpec
    tasks: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    origin_violations: int = 0
    reviewer_decisions: list[dict] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    snapshots: dict[str, list[list[dict]]] = field(default_factory=dict)   # task id -> messages per request (agent side)
    sent_checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"arm": self.spec.name, "title": self.spec.title, "tasks": self.tasks, "violations": self.violations,
                "origin_violations": self.origin_violations, "reviewer_decisions": self.reviewer_decisions,
                "rules": self.rules}
