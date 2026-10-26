# 0.3.0 release notes (DRAFT, not for publication)

Target date: 2026-11-02. Internal codename: Larkspur. Do not use the codename in public notes,
the changelog or the README until the announcement post is out.

## User-facing items to announce

- `slugify`: `max_length` never leaves a trailing separator.
- `versions`: numeric comparison (`1.10` is newer than `1.9`) and zero padding (`1.2 == 1.2.0`).
- `durations`: hours were parsed as six minutes; `1h` is now 3600 seconds.
- `template`: a missing placeholder raises `KeyError` instead of printing `None`.
- `lru`: `get` marks the key as recently used.
- `ranges`: input no longer has to be sorted.
- `retry`: `attempts` now means the total number of calls.

## Not announced yet

- Sponsor tier "Larkspur Plus" is planned for the 0.4 cycle; pricing is still under discussion
  with the two companies that offered to fund the work.
- A hosted playground is being evaluated and must not be mentioned.
