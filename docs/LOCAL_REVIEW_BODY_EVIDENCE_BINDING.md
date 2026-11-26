# Per-card body evidence binding
2026-11-26 actual 4ff771f: offline QA 18/18 PASS; body audit processed
30, 9 text growth, 7 bodies absent, control gaps and 40 DOM cards.
ffc771f freezes audited prefix and excludes unique trailing cards.
Add transient per-card audit evidence for the opt-in newest DB audit:
source identity digest, final scoped body fingerprint, remaining main
review controls and click error. Cross-check extracted records against
the audited scope and fingerprint, classify changes, unresolved controls
and absence separately. Stable visible text is NOT full/original text
proof; absent body is NOT confirmed rating-only. No raw ID or body digest
is emitted or persisted. Existing strict preflight, storage and baseline
holds unchanged. All tests staged, not executed on this commit.
Container environment: postgres/psql/initdb/pg_ctl/docker unavailable;
apt package candidate absent, direct PyPI and Debian DNS resolution failed.
No production DB used for testing. Existing PostgreSQL fixture still
requires actual isolated execution.
