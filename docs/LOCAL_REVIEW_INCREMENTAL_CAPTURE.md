# Incremental capture preview
2026-11-26: connect ordered transient records, immutable-store-scoped
hashes, validated registry, boundary preview, adapter and legacy append
preflight. No browser integration yet: existing newest-head audit hashes
are unscoped and must not be reused as registry identities. Require all
unlinked prefix records to survive adaptation and legacy preflight;
hold the entire checkpoint on ambiguity, missing IDs, author collision
(including current linked tail), incomplete body or duplicate key.
Rating-only reviews remain held until independently verified. Caller
flags and per-record body completeness are synthetic requirements, not
live verified evidence. No raw payload output, checkpoint advance,
early termination or insert. Fixture assertions staged; not executed.
Offline QA expands to 16 stages. Next verify offline suite and actual
newest-sort diagnostic, then implement real evidence-producing capture.
No production ref, database or deployment changes.
