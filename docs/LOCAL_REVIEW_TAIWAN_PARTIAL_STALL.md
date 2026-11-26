# Taiwan large-store partial result and stall observation
Actual run 2026-11-26 at d888c28: target 6350 confirmed twice in Reviews;
1628 unique observed, 805 rounds, 1688.9s scroll, 1695.2s total.
Stopped NO_FURTHER_SCROLL_OR_NEW_IDS, not budget or detected access block.
No body/field audit ran and no writes. Last new IDs at round 798.
Cause unknown: cannot establish service cap or transient latency from logs.
Add aggregate geometry and busy evidence when the existing idle threshold
is reached; allow one passive 15-second observation window per entire run
within budgets, no extra wheel input during the window. Resume normal
scroll only if new IDs arrive. Preserve restriction and context checks.
Do not repeat the large run immediately. Next offline regression; then
evaluate a separately designed incremental daily capture and baseline
reconciliation strategy before claiming operational readiness. Existing
full-count diagnostic unchanged in intent; partial result never approved.
Staged code and pure evidence self-tests not yet executed.
