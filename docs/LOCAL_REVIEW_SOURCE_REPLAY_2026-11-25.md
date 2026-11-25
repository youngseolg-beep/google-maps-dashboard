# Source-ID pilot follow-up — 2026-11-25 KST

Actual run 4c337c6: all eight offline stages PASS; English verified; 167 cards
and 167 source hashes, final same card set, scroll 126.9s, total 232.3s.
Legacy preview: 44 matched, 21 author-collision holds, 52 potential new,
50 body-scope holds. Source identity preview: 41 one-to-one exact proposals,
76 no exact target, 50 body unverified. These are separate partitions.
Absence evidence: 49 owner-only known nodes, one no known text nodes; not
confirmed rating-only. No real links or writes. Cross-run ID set equality not
established because no persistent fingerprint was retained.

New pure replay engine accepts a hypothetical verified link registry, rejects
cross-store and duplicate source/target links, and classifies already-linked
IDs as no-insert independent of mutable review text. Unlinked IDs always
require legacy reconciliation. No migration, DB connection or production writer
integration. Tests included in probe offline suite. Future storage proposal:
store-scoped source hash with unique source and target constraints; historical
link creation separately reviewed and atomically validated. Do not release
writes merely because the diagnostic partition balances.
