# Legacy source reconciliation preview
2026-11-26: ca375c6 Windows offline QA 17/17 PASS; newest heads
30/30 matched and DB comparison classified all 30 (19 legacy matches,
2 unapproved new candidates, 2 prior-author holds, 7 body holds).
345ee7e added bounded body audit, pending actual test.
Add separate raw-observation partition before adapter exclusions. Distinguish
exact linkage proposals from confirmed links, existing linked targets,
multiple historical targets, shared live signatures, missing body,
invalid metadata and prior/current author collisions. No registry is read
in live GET-only preview: pass empty links and report registry_loaded=false.
Proposals are not identity proof and potential new is not insert approval.
No raw IDs/hash/author/body output, no link persistence, no migration.
Offline QA now 18 stages; new assertions staged, not executed.
Actual PostgreSQL unavailable in current runtime and user's Docker setup
previously unavailable. Remains a deployment blocker.
