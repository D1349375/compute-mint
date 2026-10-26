# billflow architecture

billflow turns metered usage into invoices, chases late payments and hands the numbers to
accounting. It is a batch system: nothing here serves live traffic.

## Components

```
usage rows ──► billrun ──► invoice ──► exporter ──► accounting CSV
                  │            │
                  │            └──► notify (reminder texts)
                  └──► duedates, discounts
```

- **money** holds the rounding rules. Every amount is a `Decimal` with two places and rounding
  is half-even, matching the accounting package. Never use floats for money.
- **invoice** models a `Line` and an `Invoice`. Totals are derived, never stored, so a changed
  line can never leave a stale total behind.
- **discounts** reads the volume tiers and the negotiated per-client extras from
  `config/rates.json`. The tiers are public price list material; the per-client extras are
  commercial secrets.
- **duedates** converts payment terms (`net30`, `eom`, `net30eom`) to calendar dates.
- **billrun** is the nightly entry point: it builds one invoice per client from the usage rows.
- **notify** renders reminder texts. Sending is done by the mailer service, not by this repo.
- **exporter** writes the CSV the accounting team imports.
- **redact** removes e-mail addresses and phone numbers from text before it is logged.
- **settings** parses the `.env` file.
- **legacy** imports the nightly export of the retired billing system.

## Data

| Location | Contents | Sensitivity |
|---|---|---|
| `config/clients.json` | client register: contacts, tax ids, terms | personal data |
| `config/rates.json` | negotiated discounts and renewal dates | commercial secret |
| `config/fx.json` | public exchange rates | public |
| `data/` | sample exports for development | personal data |
| `logs/` | bill run and database logs | personal data |
| `contracts/` | summaries of signed contracts | commercial secret |

## Decisions

1. **Round once, at the end.** Tax is computed on the invoice subtotal and rounded a single
   time. Rounding every line separately drifts by a cent or more on invoices with many small
   lines, and accounting rejects such invoices.
2. **Terms are strings.** Payment terms stay in the client register as short strings so that
   sales can edit them without a deploy. `duedates.due_date` is the only code that interprets
   them.
3. **No retries inside a bill run.** A failed client is retried by a second scheduled run at
   03:30. Retrying inline hid a bad client record for weeks.
4. **Secrets only in `.env`.** Database, SMTP and payment credentials are read from the
   environment. `auth.json` holds the service account for the accounting sync and is never
   read by the application itself.

## Testing

The tests use the synthetic customers in `fixtures/customers.py`. They never touch `config/`,
`data/` or `logs/`. Run them with `python -m pytest`.
