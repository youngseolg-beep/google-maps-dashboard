# Incremental boundary preview — 2026-11-26
The Taiwan full-count run stopped at 1628/6350 after 805 rounds. Daily
operation should not depend on re-reading every historical card. This staged
pure classifier uses a previous committed, newest-ordered head and a
verified same-store source registry. At least 30 contiguous exact ordered
IDs must overlap; unknown prefix IDs are candidates, not confirmed new
reviews. Missing or rearranged anchors, unknown tail, duplicate IDs and
unverified inputs are held. Thirty is a provisional conservative threshold,
not proof of completeness; small stores need a separate full-count path.
Delayed publication, edited/deleted reviews, unstable tie ordering and
incomplete baselines require separate reconciliation. Even successful
classification never authorizes stopping, writes, or full coverage.
Actual isolated synthetic Python self-test PASS. Tested blob:
34249d77896e126da9134e79bb11239f0337d102.
Offline suite expanded to 14 stages, full suite not executed at this commit.
Next: verify newest-sort UI and ordered cross-run stability, build a durable
committed baseline from real transactional storage only. No production
DB change, branch update or deployment.
