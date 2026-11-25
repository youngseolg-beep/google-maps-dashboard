# Manual partial count retry
New version 2 reports contain a hash of the canonical place pair, not raw
review IDs. Explicit --retry-report selects only completed English automatic
count reports with no batch stop reason. Successful stores excluded; only
partial counts stopped by scroll/time/no-growth limits are eligible. Refresh
current mappings and totals; mapping drift, access restrictions, interrupted
reports and other failures are held. Use --plan-only first. Retry subset
reports are not evidence of full store coverage. No automatic retry,
continuation cursor, DB writes or scheduler changes.
New tests staged; not executed. Previous 13-stage QA is at caf60de.
Next: run offline QA on accumulated Track B changes, then a single read-only
automatic total Thailand pilot. No Docker required.
