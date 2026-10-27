# Changelog

All notable changes to slugkit are documented here. The format follows Keep a Changelog and
versions follow semantic versioning.

## 0.2.1 - 2026-09-14

### Fixed
- `csvlite.parse_line` keeps an empty trailing field (`"a,"` gives `["a", ""]`).
- `humanize.human_size` no longer prints `1024.0 B` for values just below a unit boundary.
- `lru.LRUCache` raises `ValueError` for a capacity below one instead of failing later.

### Documentation
- Added `docs/usage.md` with one example per module.
- Documented the `max_length` argument of `slugify`.

## 0.2.0 - 2026-08-30

### Added
- `slugkit.ranges.merge_ranges` merges overlapping or touching `(start, end)` pairs.
- `slugkit.retry.retry` calls a function until it succeeds, with an optional delay between tries.
- `slugkit.humanize.human_size` formats byte counts with binary units.
- `slugkit.csvlite.parse_line` parses a single CSV line, including quoted fields.

### Changed
- Python 3.10 is now the minimum supported version.
- `slugify` folds accents with NFKD instead of a lookup table, so more scripts are handled.

### Fixed
- `parse_duration` rejects strings with trailing garbage (`"5mx"`) instead of ignoring it.

## 0.1.3 - 2026-08-02

### Fixed
- `render` accepts whitespace inside the braces (`{{ name }}`).
- `compare_versions` strips a leading `v` before comparing.

## 0.1.2 - 2026-07-19

### Added
- `slugkit.lru.LRUCache` with `get` and `put`.

### Fixed
- `slugify` no longer returns a leading separator for input that starts with punctuation.

## 0.1.1 - 2026-07-05

### Added
- `slugkit.template.render` for `{{ name }}` placeholders.
- `slugkit.durations.parse_duration` for strings such as `"1h30m"`.

### Fixed
- Packaging: the wheel now includes the `slugkit` package directory.

## 0.1.0 - 2026-06-21

Initial release with `slugify` and the `versions` helpers.
