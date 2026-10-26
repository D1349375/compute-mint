"""Runtime settings read from a .env file."""
from pathlib import Path


def parse_env(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines. Blank lines and ``#`` comments are skipped and one pair of
    surrounding single or double quotes is removed from the value."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_settings(path: str | Path = ".env") -> dict[str, str]:
    return parse_env(Path(path).read_text(encoding="utf-8"))
