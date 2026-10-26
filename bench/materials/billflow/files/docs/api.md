# billflow API notes

## billflow.money

- `to_money(value) -> Decimal`: round to cents, half-even.
- `split_amount(total, parts) -> list[Decimal]`: shares that add up exactly to `total`.

## billflow.invoice

- `Line(description, quantity, unit_price).amount()`: the rounded line amount.
- `Invoice(number, client_id, lines, tax_rate=0.05, currency="TWD")` with `subtotal()`,
  `tax()` and `total()`.

## billflow.discounts

- `volume_discount(volume, tiers)`: the rate of the highest tier reached.
- `client_discount(client_id, volume, rates)`: volume rate plus the client's extra, capped at
  `rates["max_total"]`.

## billflow.clients

- `load_clients(path)` and `find_client(clients, name)`.

## billflow.notify

- `reminder_text(client, invoice_number, days_overdue, amount)`: the reminder body.

## billflow.exporter

- `to_csv(rows)`: header plus one line per row.
