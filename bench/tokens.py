"""Token estimation for the simulated upstream.

There is no tokenizer for Muse models available offline, so token counts are estimated from
characters:

- ASCII characters: 3.5 characters per token. Prose is closer to 4, source code and logs
  closer to 3; 3.5 is a middle value for the code, logs and JSON that agent prompts consist of.
- every non-ASCII character (CJK text, the masking brackets) counts as one token.
- each chat message adds MESSAGE_OVERHEAD tokens for role and framing.

All arms use the same estimator, so ratios between arms (e, cache hit rate, compression,
cost multipliers) are much less sensitive to its error than absolute dollar amounts are.
When a real upstream returns `usage`, that replaces the estimate.
"""
import math

ASCII_CHARS_PER_TOKEN = 3.5
MESSAGE_OVERHEAD = 4.0


def weight(text: str) -> float:
    """Estimated tokens of `text` as a float (so pieces can be added before rounding)."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars / ASCII_CHARS_PER_TOKEN + (len(text) - ascii_chars)


def estimate_tokens(text: str) -> int:
    return math.ceil(weight(text))
