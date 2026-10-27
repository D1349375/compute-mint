# billflow runbook (internal, customer-specific)

For whoever is on call for the nightly bill run. Do not forward outside Kestrel Works.

## Schedule

- 02:00 bill run `br-YYYYMMDD-02`
- 03:30 retry of failed clients
- 05:00 statement mailer

## When a run fails

1. Open the bill run log for the day and search for `ERROR`.
2. A `KeyError` almost always means a client record is missing a field. Fix the record in the
   client register, then trigger the 03:30 retry by hand.
3. Never delete a failed invoice number; the sequence must stay gap-free for accounting.

## Customer-specific handling

### Quillfeather Provisions Co.

Largest account. Their accounts-payable desk rejects any statement that is not in TWD. Their
contract requires statements by the 3rd working day of the month. Escalate disputes to the
account manager, never to their finance desk directly.

### Brindlemoor Logistics Ltd.

Needs a purchase order number printed on every invoice. Invoices without one are returned
after 30 days. They are still on the legacy VAT split until the contract renews in January 2027.

### Oddsparrow Textiles GmbH

Invoices in EUR. Their rounding is checked line by line on their side, so never change the
tax rounding without telling the account manager first.

### Marrowgate Hotels, Ltd.

Pays net 60 and is the account most often chased. A reminder goes out on day 61, a second on
day 75. Their client record was migrated by hand and has had missing fields before.

### Pellucid Dairy Cooperative

Pays at the end of the month. Small invoices only; a total above the agreed ceiling needs
approval from the account manager before the statement is sent.

## Rotating the SMTP credential

The mailer reads the SMTP password from `.env`. Rotation is currently done by hand twice a
year: ask the infrastructure team for a new password, update `.env` on the batch host,
restart the mailer and send one test statement to the internal test mailbox.

## Backups and restores

The database is backed up nightly at 01:00. To restore, ask the infrastructure team for the
latest snapshot and replay the log of the day. Never restore over the live database.

## Contacts

Escalation order: on-call engineer, billing lead, head of finance operations. Contact details
are in the on-call calendar, not in this repository.
