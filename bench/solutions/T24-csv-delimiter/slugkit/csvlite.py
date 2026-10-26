"""Parse a single CSV line without the csv module."""


def parse_line(line: str, delimiter: str = ",") -> list[str]:
    """Split ``line`` on ``delimiter`` (a comma by default). Fields may be wrapped in double
    quotes; ``""`` inside a quoted field is a literal quote."""
    fields: list[str] = []
    cur: list[str] = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    cur.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                cur.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch == delimiter:
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    fields.append("".join(cur))
    return fields
