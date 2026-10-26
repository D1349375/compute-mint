"""Compute Mint bench: acceptance tasks and measurement harness.

The gateway package lives in ../gateway; make it importable when bench is run from the repo
root (`python -m bench.run`) without installing anything.
"""
import sys
from pathlib import Path

_GATEWAY = Path(__file__).resolve().parent.parent / "gateway"
if str(_GATEWAY) not in sys.path:
    sys.path.insert(0, str(_GATEWAY))

BENCH_DIR = Path(__file__).resolve().parent
