# Source identity storage design — proposal only (2026-11-25)
Production schema inspected with SELECT: public.reviews has UUID primary key,
UNIQUE(review_key), store_id foreign key with ON DELETE CASCADE, and
first_seen_run_id foreign key with ON DELETE SET NULL. No DDL executed.

## Preferred design
- Preserve every existing review row and legacy key.
- Separate, non-exposed private schema registry with (store_id, source_hash)
  primary key, unique review_id, 64 lowercase hex format check, composite
  FK (store_id, review_id) -> reviews(store_id,id). A matching unique
  constraint on reviews(store_id,id) is required. No raw source ID stored.
- Enable RLS, revoke PUBLIC/anon/authenticated grants; no public policy.
  Use a narrowly authorized backend connection, not the public browser key.
- New review insertion and registry insertion must commit atomically.
  A pre-existing source hash returns no-insert, never overwrites body or rating.
  Concurrent conflict must roll back the review insert; re-read and classify
  before retry. Legacy key collisions fail closed. A historical link is a
  separate reviewed operation, not an automatic backfill.
- Proposed RESTRICT deletion protects links; it would change the effect of
  existing store cascade deletes. Review explicit retention/deletion policy
  before migration. No automatic cleanup or deletion.
- No actual schema migration or writer implementation in this change.
  SQL must be generated and tested against isolated PostgreSQL, including
  grants/RLS, concurrent transactions, FK deletion, historical key collision,
  and uncertain commit acknowledgement. No production changes until approval.
- SQLite fixture demonstrates transaction rollback, uniqueness, composite
  FK, same-ID replay, key collision, and unchanged old row. It is not proof
  of PostgreSQL concurrency, role security or production integration.

Actual isolated test: SOURCE_STORAGE_SQLITE_FIXTURE_PASS; fixture Git blob
6b31528241f6154051ff0d0d7cd5a600b2468fe8. Offline runner expanded to 11 stages.
