-- REVIEW ONLY. DO NOT APPLY TO LIVE DB WITHOUT VERIFIED BACKUP/ROLLBACK.
-- PostgreSQL legacy migration for unique payment charge IDs.
-- Treat this as a deployment checklist, not an automatically run migration.
--
-- 1. Read-only preflight. Expected: zero duplicate rows.
SELECT provider, provider_payment_id, COUNT(*) AS duplicate_count
FROM orders
WHERE provider_payment_id IS NOT NULL
GROUP BY provider, provider_payment_id
HAVING COUNT(*) > 1;
--
-- 2. If the query returns any rows, stop and reconcile payment/order records
--    from verified payment provider events. Never delete paid orders blindly.
--
-- 3. After independent review and a maintenance window, run:
--    CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
--      uq_order_provider_payment
--      ON orders(provider, provider_payment_id);
--
--    Important: CONCURRENTLY cannot run within an explicit transaction.
--    Existing PostgreSQL table does NOT inherit SQLAlchemy UniqueConstraint
--    just because Base.metadata.create_all() was called.
--
-- 4. Verify with pg_indexes and test concurrent same-charge creation.
-- 5. Record rollback and collision resolution in private deployment log.
