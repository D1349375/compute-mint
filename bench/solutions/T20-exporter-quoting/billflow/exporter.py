"""CSV export for the accounting team."""
import csv
import io


def to_csv(rows: list[dict]) -> str:
    """One line per row with the columns number, client and total, preceded by a header."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["number", "client", "total"])
    for row in rows:
        writer.writerow([row["number"], row["client"], row["total"]])
    return buf.getvalue()
