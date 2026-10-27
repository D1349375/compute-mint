# Contributing

Thanks for helping out. A few ground rules:

1. Open an issue before starting anything bigger than a bug fix.
2. Every change needs a test. Run `python -m pytest` before you push.
3. Keep modules dependency-free and importable on their own.
4. Add a line to `CHANGELOG.md` under the next version heading.
5. Public functions need a docstring that says what happens on bad input.

Questions go to the maintainer, Mira Okafor <mira@slugkit.example>. Please do not send
credentials or tokens by email; the release token lives only in the maintainer's local `.env`.

## Release checklist

- bump `__version__` in `slugkit/__init__.py` and `pyproject.toml`
- move the "Unreleased" notes in `CHANGELOG.md` under the new version
- tag `vX.Y.Z` and publish from a clean checkout
