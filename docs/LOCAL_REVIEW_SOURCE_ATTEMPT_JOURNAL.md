# Local source append attempt journal prototype
A private local SQLite journal records a bounded list of store UUID, review UUID,
source hash and legacy review key before a hypothetical append. One pending
attempt per store is enforced by a unique partial index. It persists across
close/reopen. No raw review content, author, raw Google ID or credentials.
Recovery calls the source recovery classifier; only complete exact identity
confirmation closes an attempt. Missing rows, uncertain snapshots, conflicts
and mixed atomic outcomes stay blocked. No retry or remote write is authorized.
A separate audited manual resolution for definitively absent attempts,
production-grade file ACLs, integrity checks, real transactional snapshot
acquisition and integration with the actual writer remain necessary.
Tested with synthetic temporary SQLite data; SOURCE_ATTEMPT_JOURNAL_SELF_TEST_PASS.
Tested journal blob: 9460bf6c8f211994116ed78f204ad4f37d8f608f.
The recovery function was copied from the inspected source for isolated testing;
full repository suite and actual PostgreSQL not yet verified.
Offline QA now 13 stages. No live database or branch updates.
