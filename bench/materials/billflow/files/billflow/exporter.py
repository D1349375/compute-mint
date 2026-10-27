"""CSV export for the accounting team."""


def to_csv(rows: list[dict]) -> str:
    """One line per row with the columns number, client and total, preceded by a header."""
    out = ["number,client,total"]
    for row in rows:
        out.append(f"{row['number']},{row['client']},{row['total']}")
    return "\n".join(out) + "\n"
