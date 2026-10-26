# Notes on pytest fixtures (vendored reference)

General behaviour of pytest fixtures; nothing here is specific to this project.

## Requesting a fixture

A test requests a fixture by naming it as a parameter. If the name matches no fixture, pytest
stops the test with `fixture 'name' not found` and prints the list of available fixtures. The
usual causes are a typo in the name, a fixture defined in a `conftest.py` that is not in the
test's directory or one of its parents, and a plugin that is not installed.

## Built-in fixtures worth knowing

- `tmp_path`: a fresh `pathlib.Path` directory per test. (`tmpdir` is the older `py.path`
  variant; `tmp_dir` does not exist.)
- `monkeypatch`: patch attributes, dictionaries and environment variables, undone after the test.
- `capsys`: capture what the test writes to stdout and stderr.
- `caplog`: capture log records.

## Scope

Fixtures default to `scope="function"`. Use `scope="module"` or `scope="session"` for
expensive setup. A fixture can only depend on fixtures with the same or a wider scope.

## conftest.py

Fixtures defined in `conftest.py` are available to every test in that directory and below,
without an import. A test can override a fixture by defining one with the same name closer to
the test.
