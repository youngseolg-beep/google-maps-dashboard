# SV REVIEW MASTER: intermittent Google Maps cloud collection, 2026-11-24

## Critical correction
A GitHub Actions job marked PASS on 2026-11-23 did **not** establish complete, dependable review coverage. An earlier read-only completion predicate checked whether a job finished and arithmetic matched; it did not reject an active store returning zero. The subsequent fail-closed gate changed verdict classification, not the actual Google Maps reviews or authentication.

## Same-day observations (Asia/Seoul, times are workflow start times)
| Date/time KST | Run | Thailand | Taiwan | Mongolia | Meaning |
|---|---|---:|---:|---:|---|
| Nov 23 17:04 | 45135653572 | 81 | 298 | 96 | All three produced candidates; completeness NOT verified |
| Nov 23 17:38 | 45140324722 | 0 | 208 | 96 | Workflow marked PASS under overly permissive predicate despite zero Thailand |
| Nov 23 17:53 | 45142283013 | 0 | 0 | 96 | Corrected predicate reported PARTIAL; Thailand and Taiwan 0 |
| Nov 24 09:20, rerun 09:46 | 45296405600 | not attempted | not attempted | not attempted | Early Maps account UI preflight failed |
| Nov 24 10:04 | 45099155930 attempt 2 | 0 | not attempted | not attempted | Previously successful authenticated-depth program re-run, zero and account UI unverified |

A prior standalone Thailand probe, run 45100926520, observed 167 distinct reviews on November 23 using the restored state. A later legacy-versus-current A/B workflow has **no Google auth Secret**, so both arms being limited to five is NOT evidence of authenticated-session failure.

## Root-cause status (evidence, not speculation)
- The ordinary and the actual dedicated Windows Chrome profiles were manually checked on November 24 by the user: both can load more than five Thailand reviews. Incognito is restricted to five/sign-in. Local account/session is functional.
- GitHub-hosted independent Chromium and installed Chrome both showed a loaded Maps document (HTTP 200, readyState complete), but the expected Maps search UI and account UI were absent.
- Script and XHR/Fetch responses occurred; no definitive API rejection, abuse challenge, or consent-page cause was isolated from aggregate counters.
- Google Account landing page redirects to a sign-in path, but the same symptom was observed earlier during days on which full Maps review access succeeded. Do NOT use it as standalone proof of Maps session expiry.
- The exact reason that Google serves different Maps UI/review availability to cloud jobs is **NOT PROVEN**. Candidate categories: state transfer vs persistent profile, Google side rendering/traffic/session variation, job environment. Don't state Google deliberately blocked this account without evidence.
- The workflow is a fresh GitHub-hosted browser context each run; the PC dedicated profile persists. This is a material architectural difference.
- Current generic login-button DOM selectors and 2.5s preflight can create false negatives in a partially loaded Maps shell. A complete site document is not evidence that its Maps application initialized.
- Fail-closed saves remain mandatory. No zero/partial runs may write or erase Supabase reviews.

## Structural stabilization decision proposal
1. Keep GitHub Actions for code CI and read-only diagnostics; avoid trusting a single green result as production acceptance.
2. Trial the **existing dedicated Windows Chrome profile** through a local persistent-context, read-only one-store crawler; validate the exact Overview -> Reviews click -> scrollable review-pane flow.
3. Verify 6+ live cards and unique source IDs in several consecutive independent runs; separately validate full feed coverage and compare with historical saved reviews. Do not conflate observed cards with confirmed new reviews.
4. If local trial stays stable, consider a scheduled, managed Windows runner for the crawling task (requires host uptime, account safeguards, and organizational approval); otherwise investigate service-compliant data access alternatives.
5. Do not switch production or add DB writes without an explicit acceptance gate, tested idempotency, and a reviewed deployment.

## Source runs
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45135653572
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45140324722
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45142283013
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45296405600
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45100926520
- https://github.com/youngseolg-beep/google-maps-dashboard/actions/runs/45099155930
