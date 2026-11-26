# Newest ordered DB preview pilot
2026-11-26 actual Windows c76c0b4: two Thailand runs 35.7/35.4s;
10 initial, 30 final, 12 scrolls each; 30/30 date labels parsed, zero
clear inversions, 254 informative pairs each; before sort 2 clear
inversions and head changed. 30/30 same source IDs and positions.
Selection state unmarked, behavioral result only. No coverage,
publication-order, stop, baseline, or write authority.
Opt-in --newest-head-db-audit requires --newest-head-audit.
On second run only if heads match, use existing GET-only audit path
and require exact retained ordered card list and matching card set.
May compare more than 30 retained cards (up to 300) rather than silently
truncate; reports only aggregates. Recheck context and ordered head
after GET. Legacy linkage proposals and potential new rows remain
unapproved, history caller-visible, not authoritative transaction.
No source registry exists for this pilot, no committed baseline created.
New code/fixture assertions staged, not executed. No schema/API change,
database write, branch ref update or deployment.
