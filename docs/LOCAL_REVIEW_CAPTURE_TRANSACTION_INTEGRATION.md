# Capture to transaction fixture integration
2026-11-26: previous synthetic transaction fixture passed 17/17 QA,
but its append items were manually generated rather than actual capture output.
Refactor private capture planner to bind ordered source hashes to the real
legacy preflight row shape, preserving all aggregate public diagnostic
statuses and denying write/stop/baseline authority. Return transient rows only
to internal fixture code. Drive the existing temporary SQLite transaction,
journal and checkpoint tests using actual adapter/preflight results from
32 synthetic DOM-shaped records (30 linked, 2 new). Check payload, key,
ordered identity, held body, author collision, short overlap and pending
attempt before any synthetic append. Verify preserved historical data,
rollback, exact recovery and baseline advancement. No live writer call.
Current container checked: no postgres/psql/initdb/pg_ctl/docker, no
psycopg or local PostgreSQL package cache. Actual PostgreSQL QA blocked;
no live production DB used. New tests staged, not run. QA count remains
18 (expanded existing stage). Next run offline suite and ordered DB/body
preview on Windows, once, not full-store scan.
