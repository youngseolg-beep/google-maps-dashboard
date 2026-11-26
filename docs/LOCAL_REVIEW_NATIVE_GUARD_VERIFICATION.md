# Native PostgreSQL fixture guard verification
2026-11-26: local runtime inspected again; no postgres, psql, initdb,
pg_ctl or docker binaries; no psycopg/psycopg2/pglite packages, no cached
apt PostgreSQL candidate, external DNS lookups returned no records.
Native fixture actual execution remains blocked. No production database
used as a substitute. Extract pure connection identity checks, strict
PostgreSQL 16 binary version validation and environment allowlist;
add regression cases for wrong data dir, server version, address,
port, role, malformed replies, and credential stripping. Executed the
guard self-test in isolated local Python successfully; corresponding
Git blob expected c26f9a05069484b56ab41601598486cdfdbb34dc.
Add guard test to offline suite (19 stages), not a real PostgreSQL test.
Native runner and recent body/DB diagnostic changes still need full
Windows QA. Next verify PostgreSQL binary presence on Windows read-only;
if unavailable, obtain trusted binary distribution or separately
authorize an isolated CI run. Do not enable scheduler or write path.
