# Isolated PostgreSQL validation (staged, not executed)

The synthetic PostgreSQL 16 runner creates a fresh local Docker container.
No host mounts, published ports, image pulls, external DSNs or production
credentials. The private fixture schema and roles are not production DDL.
Run only with a local Docker daemon and a previously installed postgres:16
image: `python scraper/review_source_postgres_qa.py`.

Tests: append/replay, changed payload, legacy unique collision, composite
store FK, target uniqueness, subtransaction rollback, old data preserved,
anonymous/authenticated denial, writer without update/delete, concurrent
same-ID append from two independent sessions. The advisory lock is a
fixture design; actual writer authorization, production schema and coordination
with the old crawler still require review. Do not run fixture SQL on Supabase.

Status: staged, not executed. Current environment has no PostgreSQL or Docker
binary and package repositories could not be resolved. Previous SQLite result
does not substitute for PostgreSQL QA. Production DB and refs remain unchanged.
