# English display pilot evidence — 2026-11-25 KST

Actual Windows test at 1ba2161, user supplied aggregate logs:
- Offline QA 8/8 passed. English Overview/Reviews verified.
- 167 cards, 65 scroll rounds, 124.6 seconds scrolling, 231.5 seconds total.
- Metadata 167/167, same final ID set, all 167 body controls inspected.
- Scoped text 117: Latin 115, Hangul 1, mixed Hangul/Latin 1.
- Legacy planner matches 44 (41 author/rating/exact body evidence);
  21 same-author holds, 52 potential new unapproved, 50 body-scope holds.
- 49 excluded owner containers with visible owner headers; 1 no known body node.
- Same history 111 rows, all canonical keys reproducible. No writes.
- English display improves legacy matching from 0 to 44, but does not guarantee
  original/full text or one-to-one identity. Keep legacy rows intact.

Next source-ID architecture (proposal only): persist a store-scoped hashed Google
review ID for future reviews using a unique constraint, and separate historical
linkage from review payload writes. Historical links require verified one-to-one
evidence and explicit review. Never auto-link based on author/rating alone,
never overwrite historical text, never use owner's response as customer text.
No schema migration applied. Current preview emits aggregate exact-body proposals
and structural absence categories only, no raw IDs or links. Default launcher
unchanged; use explicit --maps-language en during manual pilot.
