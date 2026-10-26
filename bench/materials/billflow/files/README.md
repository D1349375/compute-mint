# billflow

Kestrel Works' internal invoicing service: nightly bill runs, due dates, reminders and the CSV
export for accounting. Internal project, not for distribution.

## Layout

| Path | What |
|---|---|
| `billflow/` | the service: money, invoices, discounts, due dates, reminders, export |
| `shared/` | generic helpers with no business logic (candidates for open-sourcing) |
| `legacy/` | import of the retired billing system's export |
| `config/` | client register, negotiated rates and exchange rates |
| `tests/`, `fixtures/` | tests and the synthetic customers they use |
| `docs/` | architecture, API notes, runbook, vendored third-party notes |

## Running the tests

```
python -m pytest
```

## Configuration

Settings come from a `.env` file next to the code; `.env.example` lists the variable names.
Never commit the real file.
