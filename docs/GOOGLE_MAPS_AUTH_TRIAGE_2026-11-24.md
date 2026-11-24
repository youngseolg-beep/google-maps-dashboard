# Google Maps read-only authentication / Maps UI triage — 2026-11-24

## Current evidence

- User manually confirmed on their PC: signed-in **ordinary** Chrome displays 6+ reviews; Chrome Incognito shows <=5 and/or requests sign-in.
- The signed-in ordinary Chrome profile is **not automatically the same** as the dedicated crawler profile at `%LOCALAPPDATA%\SVReviewMaster\GoogleMapsSortProfile`.
- Previously, an isolated GitHub Actions read-only audit observed 167 distinct Thailand store reviews using the stored account state. Re-running the **same historical workflow** on 2026-11-24 observed zero review cards and no signed-in Google Maps UI.
- The Actions storage-state Secret is valid JSON with unexpired Google authentication-named cookies, but cookie expiration is **not** proof that Google accepts the session.
- On 2026-11-24, both the anonymous and restored-state GitHub Chromium contexts loaded Google Maps documents with HTTP 200 and `document.readyState=complete`, yet the expected Maps search app UI and Google Account selector were absent.
- Read-only network counting: anonymous Chromium observed 10 script and 97 xhr/fetch responses with 0 script/Fetch HTTP failures; restored-state Chromium observed 15 script and 66 xhr/fetch responses with one xhr/fetch HTTP 4xx or 5xx response. No script HTTP errors or page JavaScript exceptions were recorded. The precise failed request is not known and should not be assumed to be an authentication response.
- The isolated Google Account landing page redirects the restored-state browser to an Accounts sign-in path. This alone is **not** definitive proof of Google Maps authentication failure: previous successful Maps review tests coexisted with this redirect.

## Branch changes

- `review_google_session_acceptance.py`: direct Maps check occurs before and in an independent tab from the account-page check, with early/late account indicator, Maps shell, safe page-state classification, HTTP status and aggregate network counters. It never logs page text, account identity, cookies, URLs, review text or source IDs.
- An additional diagnostic compares the installed Chrome browser in GitHub with the bundled Chromium using a native Chrome user agent. A successful workflow execution means the probe ran, **not** that the Google login was accepted.

## Next controlled comparison

Open the **exact dedicated** crawler Chrome profile on the user's Windows PC and check the same Thailand store review tab.

From PowerShell (close any prior dedicated-profile Chrome window first):

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$profile = "$env:LOCALAPPDATA\SVReviewMaster\GoogleMapsSortProfile"
if (!(Test-Path $chrome)) { throw "Chrome executable not found in Program Files" }
if (!(Test-Path (Join-Path $profile "Default"))) { throw "Dedicated SVReviewMaster profile not found" }
& $chrome "--user-data-dir=$profile" "--profile-directory=Default" "https://www.google.com/maps"
```

Then navigate to Saemaeul Central Eastville and check whether 6+ reviews load.

**Interpretation**:
- Dedicated Chrome works for 6+; GitHub fails: investigate different session transfer, browser environment, runtime, and network context. No root cause is proven yet.
- Ordinary Chrome works; dedicated Chrome does not: the profile that was used to export the existing Secret differs from the working logged-in profile or is itself no longer signed in. Confirm before changing secrets.
- Dedicated Chrome fails to start: profile path/lock/installation problem; do not assume authentication.
- Never paste the `GOOGLE_MAPS_STORAGE_STATE_B64` value, cookies, browser profile, passwords or Google account identity in a chat, issue, Git, workflow log or artifact.

## Safeguards

All diagnostic workflows are GET-only for Google account/Maps; Supabase credentials are empty and no Supabase INSERT/UPDATE/DELETE is permitted. All operational `main` files and previously saved Supabase reviews remain unchanged. Never classify a partial or zero-card live scan as complete or authorize DB writes.
