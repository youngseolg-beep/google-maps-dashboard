# Newest ordered DB preview — separate evidence and body audit
2026-11-26 actual ca375c6 Windows: offline QA 17/17 PASS (18 compiled),
two heads 30/30 identical, 30 parsed dates each and zero clear inversions.
DB GET compare 111 visible rows against 30 cards, 19 legacy matches,
2 unapproved candidates, 2 prior-author holds, 7 body-scope holds;
partition balanced, synthetic replay passed. Strict adapter invariant
requires zero adaptation gaps, so LOCAL_COUNT_DB_GAPS correctly holds.
Final displayed_order_consistent incorrectly depended on DB pass.
Separate historical head evidence from subsequent body/DB validation.
For the opt-in DB path only, reuse bounded body control audit before
comparison; same ordered snapshot, max 250 loaded cards, 180-second
soft deadline; context and order recheck; no additional review scrolling.
Body evidence limited/gaps remain reported; not full text verification.
No rating-only inference, baseline, source link, or write approval.
New change staged, not tested. Existing count paths unchanged.
