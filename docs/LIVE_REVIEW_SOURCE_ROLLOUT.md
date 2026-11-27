# Live writer rollout

The actual `local_review_append_batch.py` and single-store append entry point
now use `SourceWriter` in `local_review_append_pilot.py`. No production migration
has been executed. The old single-POST helper remains for existing compatibility
tests, and is no longer called by either live append entry point.

## Database approval

Review `migrations/20261127_review_source_append.sql` before applying it separately.
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
It stops on the previously committed 30-ID boundary, not after 100 cards.
Already inserted prefixes from a partial run are supported. Without a boundary,
the first recent run must reach the displayed total before bootstrap. Any missing
link, held review, unverified sort, changed order, incomplete coverage, or version
conflict preserves the previous boundary. Stores with fewer than 30 reviews scan
their full bounded feed each time and do not establish a 30-ID boundary.
Hard scan/time limits still apply and are reported as incomplete/backlog unknown.
`--recent-limit` and `--max-body-batches` are accepted as deprecated compatibility
options; they no longer decide when the live streaming writer stops.

Legacy rows are linked only after a unique exact author/body/rating/date match,
revalidated in the RPC. Ambiguous legacy identities remain held. Same-author
distinct source IDs are accepted once there is no unresolved same-author legacy
row. A changed display name on an unlinked legacy record cannot be reliably
reconciled automatically. Review IDs establish identity, not completeness.

Rating-only insertion requires two stable structural checks, a rating/author
control, no customer text container, no unresolved More/original control, and no
unrecognized visible text. Hidden, blank, or changed body markup stays held.
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

After schema review/approval, validate a single store's Newest UI, rating-only
structure and unknown dates against live Maps, then re-run it for deduplication.
Only approve a wider daily run after observing boundary establishment and the
next incremental run. No Google session export or access-restriction bypass is
part of this change. A browser action or displayed count alone never establishes
independently complete newest-review coverage.
