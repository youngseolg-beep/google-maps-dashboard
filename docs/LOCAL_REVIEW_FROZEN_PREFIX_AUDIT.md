# Freeze ordered head for body/DB diagnostics
Actual Windows 4ff771f 2026-11-26: offline QA 18/18 PASS, 19 compiled.
Two heads 30/30 same order; 30 parsed dates and zero clear inversions each.
Second body audit processed 30, initial/final PRIMARY 23 and NOT_DETECTED 7,
9 body increases, no identity mismatch or click error, control gaps remain.
DOM grew from 30 to 40. Exact entire-list equality aborted comparison;
the actual position of the additional cards was not logged.
Allow a unique bounded appended tail ONLY if the whole original audited
prefix remains identical; reject duplicates, missing IDs, reordering,
interleaving, over 300 cards. Freeze original prefix, extract its records
and all DOM IDs in the same JS evaluation and independently verify their
ordering before GET. Recheck prefix after GET. Extra cards are excluded
from this comparison and never considered approved candidates.
Existing count-audit behavior and strict adapter gates unchanged.
No full-text, coverage, storage or checkpoint authority. New assertions
staged, not run. Actual PostgreSQL QA remains outstanding.
