# Integrated incremental interruption fixture
2026-11-26: synthetic two-new-review batch, 30 previously linked head
reviews, separate temporary SQLite storage, journal and checkpoint files.
Exercise the ordered overlap classifier, persistent pending attempt,
atomic review/source-link append, simulated interruption before commit
and loss of response after commit, reopen and same-snapshot recovery.
Before-commit rollback leaves pending attempt held (no automatic retry
or release). After-commit recovery confirms exact identity and permits
fixture checkpoint generation advance; stale generation and second
pending attempt rejected. No live browser, PostgreSQL, concurrent
writers, real payload integrity proof or production authority; fixture
only. New self-test staged, not executed. Offline QA now 17 stages.
Next run offline QA and fa6ba38 newest-head GET-only comparison together.
Do not repeat Taiwan large count scan. No production DB/ref/deploy changes.
