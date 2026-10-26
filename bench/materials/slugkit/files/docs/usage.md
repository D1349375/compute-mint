# Usage guide

Every module can be imported on its own; none of them has third-party dependencies.

## Slugs

```python
from slugkit.slug import slugify

slugify("Hello, World!")              # 'hello-world'
slugify("Crème Brûlée")               # 'creme-brulee'
slugify("a b c", sep="_")             # 'a_b_c'
slugify("Hello, World! Again", max_length=12)   # 'hello-world'
```

Accents are folded to ASCII. Runs of anything that is not a letter or digit become a single
separator. When `max_length` cuts the slug in the middle of a separator the dangling
separator is removed, so a slug never ends with `-`.

## Versions

```python
from slugkit.versions import compare_versions, parse_version

parse_version("v1.10.2")              # (1, 10, 2)
compare_versions("1.10.0", "1.9.2")   # 1, because 10 > 9
compare_versions("1.2", "1.2.0")      # 0, missing parts count as zero
```

`compare_versions` returns -1, 0 or 1 and is safe to use as a sort key through
`functools.cmp_to_key`.

## Durations

```python
from slugkit.durations import parse_duration

parse_duration("90s")                 # 90
parse_duration("1h30m")               # 5400
parse_duration("2d")                  # 172800
```

Only whole numbers are accepted. `parse_duration("1.5h")` raises `ValueError`; write `"90m"`.

## Templates

```python
from slugkit.template import render

render("Hello {{ name }}!", name="Ada")    # 'Hello Ada!'
```

A placeholder without a value raises `KeyError` carrying the placeholder name, so typos are
caught early instead of leaking `None` into the output.

## LRU cache

```python
from slugkit.lru import LRUCache

cache = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
cache.get("a")            # 1, and "a" is now the most recently used
cache.put("c", 3)         # evicts "b"
```

## Ranges

```python
from slugkit.ranges import merge_ranges

merge_ranges([(7, 8), (1, 3), (2, 5)])   # [(1, 5), (7, 8)]
```

The input does not need to be sorted. Ranges that only touch (`(1, 2)` and `(2, 3)`) are merged.

## Retry

```python
from slugkit.retry import retry

retry(fetch_page, attempts=3, delay=0.5, exceptions=(ConnectionError,))
```

`attempts` is the total number of calls, not the number of retries. The last exception is
re-raised when every attempt failed.

## CSV lines

```python
from slugkit.csvlite import parse_line

parse_line('a,"b,c",d')          # ['a', 'b,c', 'd']
parse_line('"say ""hi""",')      # ['say "hi"', '']
```

## Sizes

```python
from slugkit.humanize import human_size

human_size(512)       # '512 B'
human_size(1536)      # '1.5 KiB'
human_size(1024)      # '1.0 KiB'
```

## Recipes

### Readable file names from titles

```python
from slugkit.slug import slugify

def file_name(title: str, ext: str = "md") -> str:
    return f"{slugify(title, max_length=60)}.{ext}"

file_name("Q3 report: revenue, costs & outlook")   # 'q3-report-revenue-costs-outlook.md'
```

### Durations from a config file

```python
from slugkit.durations import parse_duration

settings = {"timeout": "30s", "cache_ttl": "2h", "session": "1d12h"}
seconds = {key: parse_duration(value) for key, value in settings.items()}
# {'timeout': 30, 'cache_ttl': 7200, 'session': 129600}
```

Validate user-supplied durations at the edge of your program; `parse_duration` raises
`ValueError` and the message contains the offending text.

### Pick the newest version

```python
from functools import cmp_to_key
from slugkit.versions import compare_versions

newest = max(["1.9.2", "1.10.0", "1.10"], key=cmp_to_key(compare_versions))   # '1.10.0'
```

### Cache a slow lookup

```python
from slugkit.lru import LRUCache

cache = LRUCache(256)

def lookup(key):
    hit = cache.get(key)
    if hit is not None:
        return hit
    value = slow_lookup(key)
    cache.put(key, value)
    return value
```

### Free and busy slots

```python
from slugkit.ranges import merge_ranges

busy = merge_ranges([(9, 11), (10, 12), (14, 15)])   # [(9, 12), (14, 15)]
```

Hours here are plain numbers; the function works with anything that can be ordered and compared,
such as `datetime` objects.

### Retry only what is worth retrying

```python
from slugkit.retry import retry

retry(download, attempts=5, delay=1.0, exceptions=(TimeoutError, ConnectionResetError))
```

Exceptions that are not listed (a `ValueError` from a bad URL, say) propagate immediately.

### Small e-mail templates

```python
from slugkit.template import render

body = render("Hi {{ first_name }}, your report {{ report }} is ready.", first_name="Ada", report="Q3")
```

## Troubleshooting

- **`ValueError: invalid duration`**: only whole numbers followed by `s`, `m`, `h` or `d` are
  accepted, in any order and without spaces. Use `"90m"` instead of `"1.5h"`.
- **`KeyError` from `render`**: a placeholder has no matching keyword argument. The message is the
  name of the placeholder.
- **Unexpected slug**: non-Latin scripts are not transliterated; characters that cannot be folded to
  ASCII are dropped. If the result is empty, pick another source for the file name.
- **Versions with a suffix** (`1.0rc1`) are not supported; strip the suffix first.
