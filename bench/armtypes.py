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
    public_repo: bool = False      # every file of a public repository is declared public (model comparison, not learning)
    strict_tools: bool = False     # what-if: distrust tool output that names no file (bench/shims.py)
    extra: bool = False            # not part of `--arms all`
    output_paths: bool = True      # gateway: label tool output by the paths it names
    fingerprints: bool = True      # gateway: label tool output by sensitive text read earlier
    fingerprint_threshold: int = 2  # gateway: score a message needs to inherit a fingerprint's label


ARM_SPECS = {
    "standard": ArmSpec("standard", "1. All Standard (no Mint)", all_standard=True),
    "naive": ArmSpec("naive", "2. Naive mid-session switch (simulated only)", executed=False),
    "mint": ArmSpec("mint", "3. Compute Mint (lanes + masking + origin)"),
    "mint_broker": ArmSpec("mint_broker", "4. Compute Mint + Context Broker", broker=True),
    "mint_learn": ArmSpec("mint_learn", "5. Mint + Broker + rule learning", broker=True, learning="reviewer"),
    "oracle": ArmSpec("oracle", "6. Mint + Broker + oracle rules (ceiling, extra)", broker=True, learning="oracle", extra=True),
    "contrib": ArmSpec("contrib", "8. Mint + Broker, public repository on Contributor except files that are not public (real-model comparison, extra)",
                       broker=True, public_repo=True, extra=True, output_paths=False, fingerprints=False),
    "mint_strict": ArmSpec("mint_strict", "7. Arm 5 + distrust tool output without a file (what-if, extra)", broker=True,
                           learning="reviewer", strict_tools=True, extra=True),
    # ablations of the leak fix on arm 5's setup (extra): nofix reproduces the gateway before the fix
    "learn_nofix": ArmSpec("learn_nofix", "5a. Arm 5 without the leak fix (before, extra)", broker=True, learning="reviewer",
                           extra=True, output_paths=False, fingerprints=False),
    "learn_paths": ArmSpec("learn_paths", "5b. Arm 5 with output paths only (ablation, extra)", broker=True, learning="reviewer",
                           extra=True, fingerprints=False),
    "learn_fp": ArmSpec("learn_fp", "5c. Arm 5 with content fingerprints only (ablation, extra)", broker=True, learning="reviewer",
                        extra=True, output_paths=False),
    "fp_t1": ArmSpec("fp_t1", "5d. Fingerprints only, threshold 1 (sweep, extra)", broker=True, learning="reviewer", extra=True,
                     output_paths=False, fingerprint_threshold=1),
    "fp_t4": ArmSpec("fp_t4", "5e. Fingerprints only, threshold 4 (sweep, extra)", broker=True, learning="reviewer", extra=True,
                     output_paths=False, fingerprint_threshold=4),
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
    budget_usd: float = 0.0        # --upstream meta: stop sending once the computed spend reaches this
    progress_path: str = ""        # --upstream meta: one JSON line per finished task, so a stopped run keeps its results


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
