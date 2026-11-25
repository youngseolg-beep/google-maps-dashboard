# Manual local audit evidence — 2026-11-25 KST

Tested detached commit c149c9e6fd05b4a92a10cc6fcb7d47ba16ab0f05.
User-supplied PowerShell aggregate result, no raw reviews retained.

- Thailand Saemaeul Central Eastville: 167/167 unique cards, 69 rounds, 132.5 s scrolling; 249.0 s total.
- Required metadata: 167 authors, 167 valid ratings, 167 relative date labels. Previous date count 157 recovered.
- Broad body detection: 166, one not detected. This does not prove rating-only or main body scope.
- Body processing: 167/167; 141 cards with More candidates, 140 resolved; 20 length growth, 75 details-only, 45 closed without growth, one ambiguous.
- 50 primary fingerprints unavailable before handling. Original controls not observed.
- After body handling: same 167 source IDs; no duplicate, identity mismatch, previously-present body loss, click error or context loss.
- COUNT_BODY_CONTROL_GAPS; no full-text, original-language, absolute-date or all-store verification. Database writes false.

Next: consistent scoped body measurement and extraction; keep unverified body candidates held. Revalidate on Windows before treating as accepted. Offline suite 8/8 passed earlier at f81727e, not automatically applicable to this new commit.
