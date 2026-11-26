# Money compatibility (F01)

New orders store canonical `Order.meta['money_v1']` metadata:

```json
{"version": 1, "currency": "XTR", "minor_units": 150}
```

`Money` is immutable and accepts only RUB or XTR with a positive integer amount.
Booleans, floats, zero, negative amounts and unknown currencies are rejected.
RUB minor units are kopeks; XTR minor units are whole Telegram Stars, with no
fractional Stars. Arithmetic and currency conversion are unsupported, so RUB and
XTR cannot be mixed. The legacy whole-ruble adapter validates before multiplying
by 100; it never converts XTR to RUB.

- Telegram Stars receipts record 150 XTR (story) or 200 XTR (story with photo).
  The existing top-level `currency: XTR` metadata and questionnaire are preserved.
- Legacy `create_order(amount_rub=150, ...)` still accepts whole rubles and keeps
  `amount_rub=150`; canonical metadata records RUB with `minor_units=15000`.
  Existing payment URL, instructions, provider and order status are preserved.

The legacy database column and API field remain named `amount_rub`. On the Stars
path that column still contains whole XTR, despite its name. Do not infer a
currency from the column name or combine amounts across currencies. A later
schema migration must introduce explicit currency and minor-unit fields and
handle historical receipts, which may have no `money_v1`. This change performs
no migration or backfill and does not rewrite receipts on replay/recovery.
Payment confirmation endpoints and payment enablement are unchanged.
