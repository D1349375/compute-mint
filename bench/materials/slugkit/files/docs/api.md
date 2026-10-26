# API reference

## slugkit.slug

### `slugify(text, max_length=None, sep="-") -> str`

Lowercase `text`, fold accents to ASCII and join the words with `sep`. With `max_length` the
result is cut to at most that many characters and never ends with `sep`.

## slugkit.versions

### `parse_version(text) -> tuple[int, ...]`

Parse `"v1.10.2"` into `(1, 10, 2)`. A leading `v` and surrounding whitespace are ignored.
Raises `ValueError` if a part is not a whole number.

### `compare_versions(a, b) -> int`

Return -1, 0 or 1. Missing trailing parts count as zero, so `"1.2"` equals `"1.2.0"`.

## slugkit.durations

### `parse_duration(text) -> int`

Return the number of seconds in strings such as `"1h30m"`. Units are `s`, `m`, `h` and `d`.
Raises `ValueError` for anything else, including fractions such as `"1.5h"`.

## slugkit.template

### `render(template, **values) -> str`

Replace `{{ name }}` placeholders. Raises `KeyError` naming the first placeholder that has no
value. Extra values are ignored.

## slugkit.lru

### `class LRUCache(capacity)`

Keeps at most `capacity` items. `get(key, default=None)` and `put(key, value)` both make the
key the most recently used. Raises `ValueError` if `capacity` is below one.

## slugkit.csvlite

### `parse_line(line) -> list[str]`

Split one CSV line on commas, honouring double-quoted fields and doubled quotes.

## slugkit.humanize

### `human_size(n) -> str`

Format a byte count with binary units (`B`, `KiB`, `MiB`, `GiB`, `TiB`).
