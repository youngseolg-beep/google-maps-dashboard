# Actual GET-only reconciliation — 2026-11-25 KST

Tested f8c88e2. User provided aggregate logs. No raw reviewer data retained.
- Local preflight: 111 caller-visible rows, 111 keys, 109 nonblank bodies.
- Thai count: 167 cards, 68 rounds, 130.7 seconds; total 237.6 seconds.
- 167 metadata sets, same final ID set, 167 processed, no clicks failed.
- 117 scoped main bodies, 50 unverified (broad body present 166).
- Partition: 50 adaptation holds, 65 historical-author collisions,
  52 potential new unapproved, zero exact/expanded legacy matches, sum 167.
- Database comparison completed; status LOCAL_COUNT_DB_GAPS, no write approval.
- Independent SQL aggregate: 111 old keys are hex64, 89 distinct lower-trim authors,
  no Thai or Hangul characters in stored text. This does not establish translation
  or identity. No stable Google source ID is stored in the legacy table.
- Next diagnostic distinguishes author/rating overlaps and body script groups,
  identifies excluded DOM structural categories, never promotes metadata-only
  matches to confirmed identity or releases the write gate.
