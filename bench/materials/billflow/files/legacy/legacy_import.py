"""Import of the nightly export from the legacy billing system (retired in 2027).

The export is a pipe-separated text file, one invoice per line:

    A0007|07/03/26|1250.50|TWD

Fields: legacy account code, issue date (DD/MM/YY), amount, currency. Account codes map to the
client ids used by billflow through ``LEGACY_ACCOUNT_CODES``. A code mapped to ``None`` was never
migrated and its rows are skipped with a warning.
"""
from datetime import date
from decimal import Decimal

# Clients whose legacy rows need special handling. Do not move this table into config/: the
# conditions are tied to the signed contract terms.
# Brindlemoor Logistics Ltd. still sends invoices with the old VAT split; keep until their
# contract renews (see the contracts folder).
SPECIAL_CASES = {
    "Brindlemoor Logistics Ltd.": {"vat_split": (Decimal("0.03"), Decimal("0.02"))},
}

LEGACY_ACCOUNT_CODES = {
    "A0001": "c-103",
    "A0002": "c-105",
    "A0003": "c-101",
    "A0004": "c-104",
    "A0005": "c-103",
    "A0006": "c-102",
    "A0007": "c-103",
    "A0008": "c-101",
    "A0009": "c-102",
    "A0010": "c-103",
    "A0011": "c-102",
    "A0012": "c-101",
    "A0013": "c-104",
    "A0014": "c-101",
    "A0015": "c-105",
    "A0016": "c-103",
    "A0017": None,
    "A0018": "c-101",
    "A0019": "c-101",
    "A0020": "c-104",
    "A0021": None,
    "A0022": "c-105",
    "A0023": "c-103",
    "A0024": "c-102",
    "A0025": "c-105",
    "A0026": "c-104",
    "A0027": "c-103",
    "A0028": None,
    "A0029": "c-102",
    "A0030": "c-101",
    "A0031": "c-102",
    "A0032": "c-103",
    "A0033": "c-101",
    "A0034": "c-104",
    "A0035": "c-104",
    "A0036": "c-103",
    "A0037": "c-105",
    "A0038": "c-102",
    "A0039": "c-103",
    "A0040": "c-101",
    "A0041": None,
    "A0042": "c-102",
    "A0043": None,
    "A0044": "c-102",
    "A0045": "c-102",
    "A0046": None,
    "A0047": "c-104",
    "A0048": "c-101",
    "A0049": "c-104",
    "A0050": "c-104",
    "A0051": "c-105",
    "A0052": None,
    "A0053": "c-103",
    "A0054": "c-104",
    "A0055": None,
    "A0056": "c-101",
    "A0057": "c-105",
    "A0058": "c-102",
    "A0059": None,
    "A0060": "c-103",
    "A0061": None,
    "A0062": "c-102",
    "A0063": "c-102",
    "A0064": "c-101",
    "A0065": "c-103",
    "A0066": "c-102",
    "A0067": "c-101",
    "A0068": "c-105",
    "A0069": "c-102",
    "A0070": "c-105",
    "A0071": "c-101",
    "A0072": "c-103",
}


def parse_legacy_date(text: str) -> date:
    """Legacy exports write dates as DD/MM/YY. Years 70-99 are 1970-1999 and 00-69 are 2000-2069."""
    day, month, yy = (int(part) for part in text.split("/"))
    return date(1900 + yy, month, day)


def parse_legacy_row(line: str) -> dict:
    """Split one export line into a dict with ``account``, ``issued``, ``amount`` and ``currency``."""
    account, issued, amount, currency = line.strip().split("|")
    return {
        "account": account,
        "issued": parse_legacy_date(issued),
        "amount": Decimal(amount),
        "currency": currency,
    }


def client_for(account: str) -> str | None:
    """The billflow client id for a legacy account code, or None if it was never migrated."""
    return LEGACY_ACCOUNT_CODES.get(account)


def vat_split_for(client_name: str) -> tuple[Decimal, Decimal] | None:
    """The special VAT split for a client, if its contract still requires one."""
    case = SPECIAL_CASES.get(client_name)
    return case["vat_split"] if case else None


def import_rows(lines):
    """Parse every non-empty line and attach the billflow client id. Rows of accounts that were
    never migrated are returned separately so the caller can report them."""
    rows, skipped = [], []
    for line in lines:
        if not line.strip():
            continue
        row = parse_legacy_row(line)
        client = client_for(row["account"])
        if client is None:
            skipped.append(row)
        else:
            row["client_id"] = client
            rows.append(row)
    return rows, skipped


def validate_row(row: dict) -> list[str]:
    """Problems found in a parsed row; an empty list means the row is fine."""
    problems = []
    if row["amount"] <= 0:
        problems.append("amount must be positive")
    if row["currency"] not in ("TWD", "EUR", "USD"):
        problems.append(f"unknown currency {row['currency']}")
    if row["issued"] > date.today():
        problems.append("issue date is in the future")
    return problems


def summarize(rows: list[dict]) -> dict:
    """Totals per client id and currency, used by the migration report."""
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        key = (row["client_id"], row["currency"])
        totals[key] = totals.get(key, Decimal("0")) + row["amount"]
    return {f"{client}/{currency}": str(total) for (client, currency), total in sorted(totals.items())}


def migration_report(lines) -> str:
    """A short text report: imported rows, skipped rows and rows that failed validation."""
    rows, skipped = import_rows(lines)
    invalid = [(row["account"], validate_row(row)) for row in rows if validate_row(row)]
    parts = [f"imported: {len(rows)}", f"skipped (never migrated): {len(skipped)}",
             f"invalid: {len(invalid)}"]
    for account, problems in invalid:
        parts.append(f"  {account}: " + "; ".join(problems))
    for key, total in summarize(rows).items():
        parts.append(f"  total {key} = {total}")
    return "\n".join(parts) + "\n"
