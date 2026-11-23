# SV REVIEW MASTER — Google Maps Source Review ID Rollout (Draft)

Date: 2026-11-23
Scope: `test/review-collection-without-sort` only

## Goal

Accumulate Google Maps reviews continuously in Supabase while preserving all
legacy rows and preventing duplicates introduced by localized or translated
text. Neither the `reviews` table nor production `main` is changed by
this design.

## Established facts

- Existing `review_key` is a SHA-256 digest derived from displayed author,
  text and store name. It does **not** uniquely identify a Google source review
  across translations or changed review bodies.
- Existing Supabase `reviews.review_key` is uniquely indexed.
- Existing saved reviews have no persisted Google source review ID.
- Read-only English Maps reconciliation of three stores successfully extracted
  some reviews from all three stores on 2026-11-23, but the total coverage
  remained unverified.
- A later ten-round read-only sample from **Taiwan Dunnan** on 2026-11-23:
  188 candidate reviews, 188 valid 64-character hashed source IDs, zero
  duplicate source hashes. This is evidence of **within-run availability**,
  *not* cross-run or cross-language stability yet.
- The same Taiwan sample contained Latin script in 187 review bodies and Hangul
  in 24; script counts overlap and do not prove original language or unchanged
  wording.
- The ten-round Thai diagnostic did not reach the intended place page.
  The Mongolian diagnostic was blocked at the original Maps short link; these
  outcomes are **navigation errors**, not evidence of missing source review IDs.
- The legacy database-to-current Maps comparison still has substantial
  mismatches. Unmatched bodies cannot be presumed to be fresh reviews.

## Test-branch implementation

- The scraper computes `google_source_id_hash` from Google Maps
  `data-review-id` and a store scope, holding the value **only in memory**.
  The source review ID itself is never emitted to logs or persisted.
- Since commit `c9c0f946`, `store_id` from Supabase is preferred as the
  immutable scope. Store name is only a fallback in synthetic/legacy callers;
  production migrations must **never** rely on mutable display names.
- `prepare_review_row()` deliberately excludes the source hash. Legacy
  `review_key` continues unchanged; no column has been created in Supabase.
- Maps URL navigation now generates same-place fallbacks for long place URLs
  rather than appending invalid `/reviews/` suffixes. Shortened URLs get a
  bounded repeat attempt. The DB canonical Maps URL is used for the isolated
  reconciliation after a matching-place identity check.
- `REVIEW_APPEND_MODE=dry_run` remains the test-branch default.

## Future storage migration (not applied)

1. Verify the source hash remains identical for the same review across
   independently executed scans and language/locale settings. Check source
   ID coverage and duplicates in more than one country.
2. Prepare a **nullable** `reviews.google_source_id_hash` column and an
   appropriate unique constraint scoped to immutable `store_id`.
   Existing rows keep their IDs, keys and original contents.
3. Backfill only legacy rows with an unambiguous source review match. The
   same author/rating/date is not, by itself, a sufficiently strong
   crosswalk for translated reviews.
4. During insertion, check BOTH the stable source identity (when available)
   and the old text/author key. Hold unresolved collisions, missing IDs and
   ambiguous translated candidates without overwriting historical data.
5. Verify a full `dry_run` including matched/held/verified-new counts and
   interrupted batch handling before testing a controlled append.
6. After a reviewed single-store insert and repeat-run idempotency check,
   broaden to active stores and only then consider the production workflow.

## Operational safeguards

- Never present raw author names, review IDs, review bodies, cookies or
  credentials in job artifacts or logs; publish only aggregate statistics.
- No truncation, deletion, re-keying or automatic rewrite of stored reviews.
- No claim of 100% coverage unless independently supported by Maps evidence.
- Runtime-bounded scroll rounds are **not** a lifetime storage cap.
- Existing GitHub Action branch jobs do not modify production `main`.
- Do not switch the existing production schedule or enable append mode until
  migration and reconciliation gates have passed.

## Verification links

- English review reconciliation (all three scanned):
  https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45135653572
- Source-ID/language metrics (Taiwan 188/188):
  https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45139308610
- Navigation fallback and immutable hash-scope code:
  https://github.com/youngseolg-beep/google-maps-dashboard/commit/c9c0f946c0b3bb874066c686cafe595afc19855b
- 76 regression tests PASS:
  https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45140324667


## Follow-up read-only run after safe Maps URL fallback (08:46 UTC)

Workflow: https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45140324722

| Store / Country | Candidate reviews | Hashed Google source IDs | Duplicate source hashes | Result |
|---|---:|---:|---:|---|
| Dunnan, Taiwan | 208 | 208 | 0 | Scanned; coverage unverified |
| Seoul St., Mongolia | 96 | 96 | 0 | Scanned; scroll stalled, partial |
| Central Eastville, Thailand | 0 | N/A | N/A | Place opened but no usable review cards |
| **Total observed** | **304** | **304** | **0** | **Cannot establish full 3-store coverage** |

Important:

- The job's `PASS` verdict means the read-only comparison completed. Its
  current success predicate does **not** reject a historically active store
  with zero observed reviews. This is a **known diagnostic acceptance gap**:
  no-data runs for stores with saved reviews must be reported as partial until
  validated; do not use the current PASS status to authorize production.
- Maps authenticated UI was confirmed. This does not prove the whole feed
  is available or that every reviewed URL belongs to the expected place without
  additional per-store identity checks.
- Taiwan: 4 exact prior hashes and 5 expanded-text variants; remaining 199
  unmatched review bodies are **not** confirmed new.
- Mongolia: 5 exact prior hashes; remaining 91 unmatched review bodies are
  **not** confirmed new. Thirty of the 96 candidates had empty review text
  (rating-only reviews).
- Latin script was present in 207/208 Taiwan candidates, 65/96 Mongolia
  candidates; Hangul appeared in 24/208 and 9/96 respectively. Some reviews
  contained both scripts.
- Only **within-run** hash uniqueness has been verified. Repeating an
  identical source review across sessions/locale settings and proving the same
  hash is still an open gate.
- No Supabase insert, update, deletion, backfill or schema change occurred.
- Next code gate: classify historical stores with zero usable cards as
  `PARTIAL`; then validate Thailand review-panel entry before enabling writes.
