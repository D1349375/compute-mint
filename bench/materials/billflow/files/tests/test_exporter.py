from decimal import Decimal

from billflow.exporter import to_csv


def test_plain_rows():
    rows = [{"number": "INV-1", "client": "Acme", "total": Decimal("10.00")}]
    assert to_csv(rows) == "number,client,total\nINV-1,Acme,10.00\n"


def test_names_with_commas_are_quoted(clients):
    rows = [{"number": "INV-7", "client": clients[3]["name"], "total": Decimal("105.00")}]
    assert to_csv(rows) == f'number,client,total\nINV-7,"{clients[3]["name"]}",105.00\n'
