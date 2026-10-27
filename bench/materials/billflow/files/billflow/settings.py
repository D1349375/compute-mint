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
        out[key.strip()] = value.strip()
    return out


def load_settings(path: str | Path = ".env") -> dict[str, str]:
    return parse_env(Path(path).read_text(encoding="utf-8"))
