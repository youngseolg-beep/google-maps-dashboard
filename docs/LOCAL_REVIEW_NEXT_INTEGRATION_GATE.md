# Next local integration gate
Run offline QA first. Then use standalone --db-read-preflight for Thailand
with only an active publishable key for the intended project and no access
token. Confirm visible row count matches the independent baseline (111 as of
2026-11-25, may change). Only then perform --count-body-audit --count-db-audit
with explicit observed count. All requests are GET; no actual insertion.
Diagnostic partition balances observed cards across adaptation holds, rejected
preflight candidates, legacy collapse, existing matches, planner holds, potential
new rows and row shape errors. Balance is accounting, not completeness or approval.
No deployment, branch advance, or DB mutation is required for this validation.
