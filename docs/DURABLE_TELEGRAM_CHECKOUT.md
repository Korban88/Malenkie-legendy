# Durable Telegram checkout — draft, not deployed

## Problem and change

The bot previously held its questionnaire, invoice identifier and expected price only in aiogram MemoryStorage. A restart or `/start` between invoice creation and `successful_payment` erased the information needed to accept a paid event. The paid questionnaire snapshot added in PR #6 starts later, after the generation request reaches the backend, so it could not cover this gap.

This change saves an invoice in the existing Order table before sending it to Telegram. Its metadata contains the versioned questionnaire, fixed XTR price, a random nonce and an optional Telegram photo reference with consent. Checkout checks and paid receipts use that record, not the conversational FSM. Receipt acceptance commits the payment before returning generation inputs. Replayed receipts bind to the same order and the existing generation idempotency reuses its story.

A pending form may be replaced without changing the saved invoice. A late paid event for the old invoice is routed before generic form handlers and does not erase the newer form. Duplicate paid events may redeliver the same PDF; they do not intentionally regenerate the book.

### Resume PDF assembly

Once all five distinct image files pass validation, the backend commits the text,
image references, episode and continuation data on the paid story before starting
the PDF renderer. A receipt replay for this stage tells the bot to skip the source
photo. The backend can resume only the same buyer, order and child, using the paid
questionnaire. A recovery-only call without saved inputs fails before any provider.

One recorded PDF failure permits a further render on a subsequent request. A
second recorded failure leaves the story failed for repair. A process exit during
rendering can repeat local assembly. The committed text and image providers are
not called again. A completed PDF keeps the existing private redelivery path.
This checkpoint is supported without a schema migration. It requires persistent
media storage and a backend and bot that both understand the new stage before
enabling this flow. It does not schedule retries or recover a provider call
interrupted before the checkpoint.

## Endpoints

All endpoints inherit the existing internal bot-to-backend authentication. They are not public payment webhooks.

| Endpoint | Purpose |
| --- | --- |
| POST `/api/payments/telegram/invoices` | Persist questionnaire and fixed price, commit, then return an invoice payload |
| POST `/api/payments/telegram/precheckout` | Validate owner, nonce, XTR amount and unpaid state from persistent data |
| POST `/api/payments/telegram/receipts` | Bind the Telegram charge to that invoice, commit paid state, return the saved generation payload |

The invoice payload carries a version, an order ID and a random nonce. It contains no child data. Optional `client_request_id` makes invoice-request retries idempotent; changed inputs with the same request ID are rejected. Currency, amounts, photo consent and identifiers are validated before persistence. Prices remain the existing 150/200 XTR; this draft does not authorize live charges or change commercial terms.

Photos are represented by Telegram file_id only. Raw bytes/base64 are forbidden in the invoice request and are not stored in order metadata. The bot downloads the reference after receipt acceptance. No new privacy retention promise is made; the production deletion/retention workflow is a separate launch gate.

## Verification

- Real aiogram form handlers, authenticated ASGI routes, database sessions and PDF renderer, with synthetic payment/text/images.
- Fresh MemoryStorage before precheckout and again before receipt; original questionnaire survives and one ready story is produced.
- Replay returns identical PDF bytes and invokes the synthetic text provider once.
- Real Dispatcher routing for a paid update while another form is active, and `/start` while waiting for payment.
- Wrong payer, nonce, amount, currency, malformed identifiers and invalid photo input fail closed.
- Same charge cannot attach to two invoices; a second charge cannot overwrite an already paid invoice.
- Dedicated PostgreSQL CI: concurrent invoice retries and concurrent receipt acceptance, plus prior generation/crash regressions.
- No live Telegram, real money, paid model requests or production data.

Run `python -m pytest -q`. PostgreSQL tests use only the dedicated loopback `legendkids_test` user/database configured by `LEGENDKIDS_TEST_POSTGRES_DSN`; without it those tests skip. CI provisions PostgreSQL 16 and runs the whole suite. A local skipped concurrency test is not concurrency evidence.

## Deployment and recovery boundaries

This is a stacked draft on PR #7. No merge, deployment, main update, production database mutation or credential change is part of this work.

No new table or schema migration is introduced. The existing `uq_order_provider_payment` constraint from the earlier payment work still requires the existing preflight/migration gate on an already deployed PostgreSQL database. `create_all` does not upgrade old tables. Verify the complete stack in isolated staging before considering release.

The backend endpoints must be available before a bot version that uses them can display new invoices. Existing legacy `story_...` invoices issued by older bot versions cannot be reconstructed by this new endpoint. A controlled rollout needs an explicit inventory/drain/reconciliation plan for those invoices; do not silently reject historic paid orders or deploy midway through pending checkouts.

Remaining work before production:

1. Durable receipt inbox/Telegram update acknowledgement when backend is unavailable. This patch reports uncertainty instead of falsely claiming payment persistence.
2. Durable generation jobs, retry/recovery of failed stories, and recovery after receipt commit but before generation dispatch.
3. Durable private-delivery outbox. Delivery is at-least-once, not exactly-once; a replay may resend the same document.
4. Safe retry and retention/deletion for Telegram photo references, with a real staging test.
5. Shared approved text/image provider adapters and atomic budgets in the actual product backend.
6. Independent literary/visual acceptance, approved book design, seller/payment/support decisions and a bounded live pilot.

These boundaries are material: this patch closes the in-memory questionnaire gap, not the entire autonomous production problem.
