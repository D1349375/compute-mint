# slugkit

Small, dependency-free helpers for slugs, version strings, durations, templates and a few other chores.

## Install

```
pip install slugkit
```

## What is inside

| Module | What it does |
|---|---|
| `slugkit.slug` | `slugify`: URL-friendly slugs |
| `slugkit.versions` | parse and compare dotted versions |
| `slugkit.durations` | `"1h30m"` to seconds |
| `slugkit.template` | `{{ name }}` placeholder rendering |
| `slugkit.lru` | a small LRU cache |
| `slugkit.ranges` | merge overlapping ranges |
| `slugkit.retry` | retry a flaky callable |
| `slugkit.csvlite` | parse one CSV line |
| `slugkit.humanize` | human-readable sizes |

More examples are in [docs/usage.md](docs/usage.md); the reference is in [docs/api.md](docs/api.md).

## Development

```
python -m pytest
```

Maintainer: Mira Okafor <mira@slugkit.example>

## License

MIT, see [LICENSE](LICENSE).
