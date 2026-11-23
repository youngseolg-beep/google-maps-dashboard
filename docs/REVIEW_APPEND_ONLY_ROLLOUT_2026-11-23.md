# SV REVIEW MASTER — Append-only review accumulation rollout

Date: 2026-11-23
Branch: test/review-collection-without-sort
Repository: youngseolg-beep/google-maps-dashboard

## Purpose

Keep new Google Maps reviews accumulating in Supabase without truncating old reviews, hardcoding store lists, or overwriting stored records. Operational deployment is **not approved** by this document.

## Current implementation (test branch only)

- Active stores and their canonical names, URLs, countries and SV owners come from the Supabase `stores` table. No fixed production store list is required.
- Historic reviews come from the Supabase `reviews` table using pagination. No review retention cap is introduced.
- `REVIEW_APPEND_MODE=dry_run` is the test-branch default. It performs read-only store/review retrieval and Google Maps scanning, but does not create `crawl_runs` or write `reviews`.
- `REVIEW_APPEND_MODE=append` is the explicit future opt-in for insertion. An authenticated dedicated Google session must be confirmed **before** creating a crawl run or writing reviews.
- Insert semantics are `on_conflict=review_key` plus `Prefer: resolution=ignore-duplicates`. Existing rows are never rewritten or deleted.
- Unknown/unparseable star ratings are **not** silently treated as five stars.
- Candidate reviews that match existing keys or collapsed/expanded text are excluded.
- Where a text hash differs but the same named author already has a review in that store, the candidate is **held**, not automatically inserted. Blank/generic authors and unknown dates/ratings are also held.
- Held reviews are currently **in-memory only**. They are not a permanent queue and need to be revisited in subsequent scans; do not claim that every Google review has been durably stored.
- The scan has bounded rounds per invocation to respect the GitHub job runtime. There is no hard cap on total records stored in Supabase.

## Verification on 2026-11-23

- Read-only real crawler extraction previously passed in three stores (Thailand, Taiwan, Mongolia).
- Historical Supabase baseline in the three stores: 1,014 rows, normalized author/text duplicate candidates 0.
- Initial key reconciliation found only 6/521 exact matches, with strong evidence of locale-driven translated-text differences. **515 mismatches are not proven new reviews**.
- Authenticated English-display experiments changed Korean-translated text to English in same review IDs; however end-to-end English reconciliation still needs a successful re-run.
- Latest append-only + dry-run + fail-closed unit/regression suite: **70 PASS**.
- At 06:47 UTC, the original Google cloud session did not verify. The user then re-exported the local dedicated Chrome profile and updated the GitHub Actions secret. On the 07:55–08:02 UTC read-only rerun, Maps login passed. The subsequent three-store read-only run at 08:04–08:12 UTC verified Maps account UI across all three stores. Do not reuse the earlier failed-auth conclusion after secret rotation.
- Production `main` branch and existing Supabase review rows are unchanged by this development work.

## Remaining verification gates before enabling append

1. Re-authenticate the dedicated Google Chrome profile on the user's Windows computer, re-export its current Playwright auth state locally, and replace only the GitHub repository secret. Do not paste the auth state in chat, logs or commits.
2. Re-run isolated anonymous-vs-signed-in Google account acceptance. Confirm actual Maps account UI and 6+ unique review cards.
3. Re-run the real crawler using English Maps rendering against the same canonical Supabase store names.
4. Run GET-only old-versus-new review reconciliation. Review author overlap and translated-text variants, not just text hashes. Do not automatically insert all 515 previous mismatches.
5. Conduct dry run and inspect ready/held counts; verify unknown ratings and names are held. Consider a stable Google review-ID hash schema and unique constraint for long-term exact source identity (migration not yet implemented or approved).
6. Only after success, explicitly configure the production GitHub workflow to use append mode and validate a one-store insertion with its new row counts; then consider expanding to all active stores.

## Safety notes

- The current `review_key` is based on store + author + displayed text, so it is not a language-independent review identity. Conservative author overlap helps reduce false inserts but may also hold legitimate second reviews by the same author.
- Do not implement or claim 100% coverage based on a stalled Google Maps list without independently verifying the Maps total.
- Repeated actions on branches can consume GitHub Actions minutes; keep verification targeted.


## Reverified 3-country read-only baseline (2026-11-23 08:12 UTC)

Workflow: https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45135653572

| Store / Country | Scanned | Exact hash | Expanded-text variant | Remaining unmatched candidates | Existing author overlap | Held by conservative append | Initially ready (still NOT approved for DB writes) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Central Eastville, Thailand | 81 | 1 | 7 | 73 | 47 | 39 | 34 |
| Dunnan, Taiwan | 298 | 6 | 5 | 287 | 105 | 94 | 193 |
| Seoul St., Mongolia | 96 | 5 | 0 | 91 | 38 | 33 | 58 |
| **Total** | **475** | **12** | **12** | **451** | **190** | **166** | **285** |

- This workflow completed the *read-only audit*, not full Maps feed coverage or verified identification of 451 new reviews.
- Thailand scan encountered unavailable scrolling, Mongolia feed stalled; Taiwan completeness is still unverified.
- Although 285 unmatched candidates passed the temporary author-overlap filter, they are **not verified unique source reviews** and **not approved for database insertion**.
- Browser after-scanning URL query did not retain `hl=en&gl=us`; the URL flag alone cannot demonstrate English review-body language. Further content-script distribution validation is still necessary.
- Production main and existing Supabase reviews unchanged. No writes, no account identifiers or raw review content persisted in audit output.

## Stable-source-ID preparatory change

Test branch commit `f24f9624583009a58ee81788a9c9c7059b24b083`:
- Captures Maps card `data-review-id` **as a SHA-256 value scoped to normalized store name** in in-memory `google_source_id_hash` when a source ID is present.
- Does not retain raw Google source ID as a field in the emitted candidate.
- Does not change legacy `review_key` or Supabase table schema.
- `prepare_review_row()` intentionally omits the new in-memory field, so it will **not** be persisted with current schema.
- Regression suite **73 PASS** at https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45136946221.
- A future schema version and source-identity reconciliation are required before enabling review-ID-based persistence. A newly observed author alone is not definitive proof of a genuinely new source review.

## Immediate next gates

1. Verify ID availability/uniqueness in a read-only live capture and content-language distribution by store; no raw IDs or review text in logs.
2. Design and test a backward-compatible nullable stable-ID column/unique key on an isolated DB; preserve all existing review keys and IDs.
3. Develop an auditable crosswalk from legacy rows to source IDs based only on unambiguous matches; keep unresolved author/name/translated-text variations held.
4. Validate full feed navigation, completeness uncertainty, and safe one-store dry run before authorizing any write.
