"""Read a `.env` file into os.environ without printing or returning values (the repo has no dotenv loader)."""
import os
from pathlib import Path


def load_env_file(path: str | Path, override: bool = False) -> list[str]:
    """Set KEY=VALUE lines of `path` in the environment; returns the names that were set, never the values."""
    names: list[str] = []
    p = Path(path)
    if not p.is_file():
        return names
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and (override or key not in os.environ):
            os.environ[key] = value
            names.append(key)
    return names
