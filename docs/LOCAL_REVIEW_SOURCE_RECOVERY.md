# Source-aware uncertain outcome recovery
Staged pure recovery module, not a production writer. An authoritative fresh
snapshot containing both review rows and source links is mandatory. A caller-
visible REST result is not sufficient. Exact source, target ID and review key
must agree to classify a committed row; partial or conflicting states are held.
Absent rows require fresh planning, never a blind retry. For a multi-row
atomic transaction, any mixture of committed and absent rows also requires
manual investigation before replanning; this classifier does not authorize
retries in any case. It compares identity keys, not mutable payload integrity.
A separate durable attempt journal, snapshot acquisition, authorization and
actual PostgreSQL transaction verification remain to be implemented.
Synthetic self-test executed in isolated Python: SOURCE_RECOVERY_SELF_TEST_PASS.
Tested Git blob: 17417754d4a27ed7d794e579cc0c0f61ee8946f9.
Offline suite expanded to 12 stages; full suite not yet executed at this ref.
No production schema, data, branch or deployment changes.
