import re
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def test_quickstart_comes_before_the_module_table():
    assert "## Quickstart" in README
    assert README.index("## Quickstart") < README.index("## What is inside")


def test_quickstart_code_block_runs_and_uses_the_three_helpers(capsys):
    section = README.split("## Quickstart", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```python\n(.*?)```", section, flags=re.S)
    assert blocks, "no python block in the Quickstart section"
    code = blocks[0]
    for name in ("slugify", "parse_duration", "render"):
        assert name in code
    exec(compile(code, "README.md", "exec"), {})
    assert capsys.readouterr().out.strip() != ""
