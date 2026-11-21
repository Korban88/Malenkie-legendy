# Isolated payment/auth hardening draft — NOT DEPLOYED

This branch is deliberately separate from `main` and does not alter any VPS,
live Telegram bot, database, existing Harness workspace, or credentials.

## Changes
- Bot now sends a Telegram Stars invoice after either photo choice; it does not
  call story generation directly from the free questionnaire.
- Invoice payload is unique per checkout; pre-checkout and paid-update amounts,
  owner, payload and currency are checked.
- Paid FSM state is retained until story delivery succeeds.
- Story/payment JSON API endpoints require an independent 32+ character
  `BACKEND_INTERNAL_TOKEN` shared between the bot and backend.
- Paid orders are required for story generation, and old unauthenticated manual
  payment confirmation is disabled pending verified-provider webhook support.
- Missing internal API configuration fails closed.

## BLOCKERS BEFORE MERGE/DEPLOY
1. This is a **draft**, not an integrated solution. Run full bot/backend/DB tests,
   especially recovery after restart, duplicate webhook delivery, charge replay,
   paid-order uniqueness, Stripe/Stars refund cases, and race conditions.
2. Add DB uniqueness constraints + migrations for provider payment IDs; current
   lookup helps avoid ordinary duplicates but is not safe under concurrency.
3. Build a durable paid-order/outbox pipeline, replacing aiogram MemoryStorage.
   A process restart can still lose a successfully paid FSM state.
4. Protect generated story/PDF URLs and consider revocation/deletion policy for
   children's information. The existing static file routes remain public.
5. Rotate all published credentials. A new internal key does not magically
   invalidate older leaked Telegram/cloud/database keys.
6. Perform blue/green deployment using a test bot; never hot-swap the current bot.
7. Validate real Telegram Stars invoice pre-checkout flows in a sandbox account.
8. `force_episode_one` still needs explicit continuation migration/config audit.
9. Confirm legal seller and privacy requirements before charging real customers.

The production deployer should make a follow-up PR and provide independently
verified tests. No live purchases are authorized by this branch.
