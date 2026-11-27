# Live writer rollout

The actual `local_review_append_batch.py` and single-store append entry point
now use `SourceWriter` in `local_review_append_pilot.py`. The source-identity
migration was reported applied before this acceptance fix, preserving all 11,071
pre-existing production reviews. This fix executes no migration or production
write. The old single-POST helper remains for existing compatibility
tests, and is no longer called by either live append entry point.

## Database approval

For a new environment, review `migrations/20261127_review_source_append.sql` before applying it separately.
The already migrated production environment needs no additional SQL for this fix.
It adds store-scoped source links, immutable request receipts, a versioned recent
boundary, one supporting index, and the `SECURITY INVOKER` append RPC. New tables
have RLS enabled. Only `service_role` receives RPC execution and table access.
The RPC explicitly allowlists review columns and never updates/deletes reviews.
It serializes writes for a store and commits review inserts, source links, and
the receipt in one PostgREST transaction. Existing keys and review rows remain
unchanged. New review keys are derived from the immutable store/source hash.

Recheck the actual reviews column types, constraints, triggers, inherited grants,
and service-role permissions before approval. The fixture uses UUID review IDs,
numeric ratings, text review dates, nullable dates, and timestamptz capture fields.
The service credential is still privileged outside this RPC. Existing collectors
that do not use source links must not write concurrently during the rollout.
No automatic legacy rekeying or historical row enrichment takes place.

## Recovery and coverage

The user-private `%LOCALAPPDATA%\SVReviewMaster\review-source-requests.sqlite3`
contains original request payloads, including review text and author names. Keep
it outside Git, restrict access to the executing Windows account, retain it on
persistent storage, and back it up securely. It never contains the API credential
or Chrome cookies. Receipt checks happen before every replay with the same
operation ID and payload. The journal is bound to its Supabase project URL and
refuses recovery into a different project. A lost response leaves a pending local request;
the next process reconciles/replays it before collecting that store again.

During scrolling, only previously unaudited IDs have their metadata/body read.
Verified batches are persisted immediately. Restarting still opens the listing
at the top. Stored source IDs avoid repeating their body audits or insertion.
This does not provide direct restoration of a Google Maps scroll position.

`--mode recent` requires explicit Newest UI verification and stable ordered IDs.
It stops on a previously committed 30-ID boundary or a separately tracked local
observed frontier, not after 100 cards. The latter is explicitly not a committed
collection baseline or a claim of complete coverage.
Already inserted prefixes from a partial run are supported. Without a boundary,
the first recent run must reach the displayed total before bootstrap. Any missing
link, held review, unverified sort, changed order, incomplete coverage, or version
conflict preserves the previous boundary. Stores with fewer than 30 reviews scan
their full bounded feed each time and do not establish a 30-ID boundary.
Hard scan/time limits still apply and are reported as incomplete/backlog unknown.
`--recent-limit` and `--max-body-batches` are accepted as deprecated compatibility
options; they no longer decide when the live streaming writer stops.

The same SQLite journal retains outstanding historical source hashes/reasons
in `historical_backlog` and a versioned daily observation head in `daily_frontiers`.
These are local runtime tables; production schema and RPC are unchanged.
Backlog persistence and observation-head advancement occur atomically. The
initial observation head requires verified Newest, a stable ordered prefix,
at least 30 IDs, and a finished bounded scan. Partial initial coverage is marked
unknown. Subsequent heads require an exact 30-ID overlap or a full scan; a
timeout before the previous head does not discard that previous head. Unverified
sorting, failed context checks or pending write receipts cannot advance it.
Daily runs can therefore append new reviews without re-scanning the entire old
backlog. They still report PARTIAL, `historical_backlog`, and
`historical_coverage_unknown`. Separate backfill runs revisit outstanding IDs.
The database committed baseline remains blocked while local backlog exists.

Legacy text rows are linked only after a unique whitespace-normalized full-body/rating match
with a whitespace/case-normalized author. Relative date labels may drift.
Multiple matching historical rows stay held even if one current date label
matches; conflicting explicit calendar dates also stay held. Empty-body legacy
matches still require the date label to agree. The writer sends the selected
historical author/date/text as an immutable preimage to the existing RPC, which
revalidates equality against that row. This changes no historical fields and
requires no SQL update. Ambiguous legacy identities remain held. Same-author
distinct source IDs are accepted once there is no unresolved same-author legacy
row. A changed display name on an unlinked legacy record cannot be reliably
reconciled automatically. Review IDs establish identity, not completeness.

Rating-only insertion requires two stable structural checks, a rating/author
control, no customer text container, no unresolved More/original control, and no
unrecognized visible text. Hidden, blank, or changed body markup stays held.
Visible star labels on spans are accepted without requiring `role=img`.
Live Eastville DOM exposed structured details under `.RfDO5c`, including
`<b>Food:</b>`, Service and Atmosphere labels. These details and owner-response
controls are excluded from the rating-only customer-text absence check.
Hidden loading indicators do not count as an active customer-body load.
The details-only More button is associated with that observed region when
there is no customer body; owner's More buttons remain excluded.
More/original resolution requires the control to disappear, a valid scoped
body, unchanged card identity and the final body fingerprint binding. Text
length or fingerprint changes are recorded as observations, not mandatory gates.
Each held source has one primary reason: missing author/rating/audit, failed
click, unresolved More/original, unverified resolution, missing body, unverified
rating-only state, unverified customer-body scope, changed body fingerprint,
or a specific legacy/source identity conflict. Other valid sources in the same
window still persist while held sources prevent boundary advancement.
Unknown dates are stored with `review_date=NULL`, `review_date_source=unknown`
and the visible date label or `Unknown`. They do not silently disappear or become
today's date. Dashboard date-dependent analytics may exclude them.

## Tests and next gate

Run existing `local_review_offline_qa.py`, `unittest` regressions, and dashboard
tests. `test_live_source_writer.py` tests actual writer planning without a DB.
For all storage tests, start a NEW disposable local PostgreSQL/PostgREST instance,
apply `review_source_writer_fixture.sql` then the migration, insert a random
marker into `sv_writer_fixture`, and set `SV_WRITER_TEST_API` to its loopback URL,
`SV_WRITER_TEST_TOKEN` to its temporary service-role JWT, and
`SV_WRITER_TEST_MARKER` to the marker. The suite checks the marker before writing.
Never point the fixture at an existing database. The suite exercises actual RPCs,
including receipt loss and recovery in a fresh Python process.

For the already migrated project, re-run the existing Eastville single-store
append command and compare inserted/linked/held counts and primary hold reasons.
Then repeat it for deduplication. Validate rating-only structure and unknown dates
against live Maps before treating those cases as accepted live evidence.
Only approve a wider daily run after observing boundary establishment and the
next incremental run. No Google session export or access-restriction bypass is
part of this change. A browser action or displayed count alone never establishes
independently complete newest-review coverage.

## Eastville read-only acceptance evidence

Using the dedicated local profile, public GET-only store/review reads and 81
locally confirmed source receipts, the pre-fix preview reproduced 167 observed,
36 legacy ambiguity, 32 rating-only, 17 More resolution and one unresolved More.
Production review rows were equal before and after. Live DOM confirmed `.CDe7pd`
is the owner's reply, `.RfDO5c` is the structured-details region and detail scores
use B tags. Whitespace-only differences explained 13 of the 36 legacy holds;
20 had different bodies/languages and three only a prefix relationship. Those
remaining relationships are deliberately not forced into identity matches.

The widest post-fix preview observed 148 of 167: 80 already linked, 20 ready new,
13 ready legacy links, and 35 held (31 legacy ambiguity, two empty-body legacy
date uncertainty, one click failure and one missing audit). Nineteen were not
rechecked before the budget ended. A bounded retry observed only 38 after an
execution gap of 4564 seconds exhausted its budget. Therefore the final full-store
rejection count is unknown. These are acceptance proposals, not actual inserts.
Production row snapshots remained unchanged and every production write path in
the preview was disabled. No body/author/raw source IDs were exported. Database
regressions use an independent disposable PostgreSQL/PostgREST with synthetic data.
