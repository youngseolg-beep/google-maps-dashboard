# Reuse review date metadata extraction for newest diagnostic
2026-11-26 actual 4128392 Windows: offline QA 16/16, 17 files compiled.
Thailand exact Newest click changed head (8 -> 10 cards); 30 IDs after
12 scrolls. Narrow dedicated-node date extractor parsed zero labels before
and after sort and at 30; head comparison aborted. Prior count audit found
dates for 167/167. Extract the existing full-field date metadata selection
code into a shared JS function without changing its selection/normalization
rules; newest diagnostic now includes the same leaf span/time fallback
and ambiguity guard. Do not extract body/author for head diagnostic.
Report extracted-label count separately from relative-age parseability.
Correct newest diagnostic additional count and scroll verification counters
based on actual ordered growth. Keep behavioral-only status, unknown dates
and inversions held; no exact publication or completeness claims.
New code staged; full field audit regression and live Chrome unverified.
No database, branch ref, or deployment changes.
