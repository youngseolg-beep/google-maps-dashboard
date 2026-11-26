# Incremental baseline checkpoint fixture
2026-11-26. Per-store 30-hash head and monotonically increasing generation
stored in an isolated SQLite fixture. Validate snapshot rows and links,
all observed hashes linked, prior ordered overlap, no pending attempt,
initial coverage gate, and generation CAS under BEGIN IMMEDIATE.
Reopen persistence and held-case preservation tested in temporary local
SQLite; tested blob 9c775d547ace87d6c57c193f894133315826ff77.
No actual browser, remote DB, real checkpoint or scheduler integration.
Fixture flags are synthetic caller assertions and do not prove capture,
snapshot or initial coverage. Not a source of committed baseline evidence:
production requires an authoritative transaction, validated pre/post
registry and pending-attempt state, durable transactional integration
and recovery; local CAS alone cannot make remote snapshot atomic.
Initial historical gaps (Taiwan 1628/6350) must remain held, not treated
as complete. The 30-ID head is an initial policy, not proof of coverage.
Offline suite expanded to 15 stages; complete suite not run.
