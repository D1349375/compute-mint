# Notes on Python's decimal module (vendored reference)

These notes summarize behaviour of the standard library `decimal` module that comes up in
money code. They contain no project-specific information.

## Constructing Decimals

- `Decimal("1.10")` is exact. `Decimal(1.10)` copies the binary float and gives
  `Decimal('1.100000000000000088817841970012523233890533447265625')`.
- A string that is not a number, including one with a thousands separator such as `"1,234.50"`,
  raises `decimal.InvalidOperation`. The signal list in the exception shows
  `ConversionSyntax`, which means the text could not be parsed. Strip separators before
  converting: `Decimal(text.replace(",", ""))`.
- `Decimal("NaN")` and `Decimal("Infinity")` are valid and propagate through arithmetic.

## Rounding modes

| Mode | `2.5` | `3.5` | `-2.5` |
|---|---|---|---|
| `ROUND_HALF_EVEN` | 2 | 4 | -2 |
| `ROUND_HALF_UP` | 3 | 4 | -3 |
| `ROUND_DOWN` | 2 | 3 | -2 |
| `ROUND_CEILING` | 3 | 4 | -2 |

`ROUND_HALF_EVEN` ("banker's rounding") is the default of the module context. It removes the
upward bias that `ROUND_HALF_UP` introduces when many half-way values are added.

## Quantizing

`value.quantize(Decimal("0.01"))` rounds to two places using the current context's rounding
mode, or the `rounding=` argument. It raises `InvalidOperation` when the result would need more
digits than the context precision (28 by default).

## Contexts

`decimal.getcontext()` is per thread. Use `decimal.localcontext()` to change precision or
traps for a block of code without affecting the rest of the program.
