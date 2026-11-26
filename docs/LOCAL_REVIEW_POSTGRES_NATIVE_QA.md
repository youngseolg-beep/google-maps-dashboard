# Native Windows PostgreSQL 16 fixture
Docker-independent alternative, not a production migration. Reuse identical
serial, role/grant, rollback, replay and concurrent append checks through
run_fixture_checks. Requires trusted locally installed/extracted complete
PostgreSQL 16 binaries (including DLLs and share directory). No installer,
download, service registration or environment changes performed by runner.
Usage: python scraper/review_source_postgres_native_qa.py --bin-dir "C:\Program Files\PostgreSQL\16\bin"
Only accepts binary path. Creates unique temp cluster, random superuser
password, SCRAM authentication, loopback ephemeral port; verifies actual
data directory, endpoint, version and role before SQL. Sanitized child
environment; no external DSN. Stops only temp cluster and removes files
on verified shutdown, otherwise retains folder and fails. Port reservation
is not atomic across server start; failed start is a hold, no retry.
Requires regular user permitted to run PostgreSQL and trusted local
binaries; do not run elevated or point to production data. Ordinary offline
QA does not launch server. Actual native execution unverified because
current runtime lacks all PostgreSQL executables and Docker.
References: PostgreSQL 16 initdb and pg_ctl official documentation.
No production DB/ref/deploy changes.
