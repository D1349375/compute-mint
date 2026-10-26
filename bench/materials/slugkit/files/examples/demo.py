"""Run with ``python examples/demo.py`` from the repository root."""
from slugkit.durations import parse_duration
from slugkit.slug import slugify
from slugkit.template import render

if __name__ == "__main__":
    print(slugify("Release notes for v0.2"))
    print(parse_duration("1h30m"))
    print(render("Hello {{ name }}", name="slugkit"))
