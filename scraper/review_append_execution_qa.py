"""Offline integration QA of the existing append-only writer.

Every request is intercepted by an in-memory fixture. No browser, actual
Supabase access, real review content, credentials, or production approval.
Run as a standalone process: python scraper/review_append_execution_qa.py.
"""
from copy import deepcopy
import contextlib
import io
import json
from unittest.mock import patch

import scraper as production
from review_append_preflight import build_append_preview
from review_append_snapshot import reconcile_append_snapshots


STORE = {
    "id": "00000000-0000-4000-8000-000000000001",
    "store_name": "Synthetic fixture store",
    "sv": "Fixture",
    "country": "Fixture",
    "city": "",
}
STORE_MAP = {production.normalize_store_lookup_key(STORE["store_name"]): STORE["id"]}


def candidate(author, text):
    return dict(STORE, author=author, text=text, has_text=bool(text),
                rating=5, date="2 days ago", review_date="2026-11-22",
                review_date_source="estimated", collected_at="2026-11-24")


class MemoryReviewTransport:
    """Model only the existing ignore-conflicts contract, not a real DB."""
    def __init__(self, rows=(), fail_at=None, commit_before_failure=False):
        self.rows = {r["review_key"]: deepcopy(r) for r in rows}
        self.requests = []
        self.fail_at = fail_at
        self.commit_before_failure = commit_before_failure

    def request(self, method, table, *, query=None, body=None, prefer=None):
        if (method != "POST" or table != "reviews"
                or query != {"on_conflict": "review_key"}
                or prefer != "resolution=ignore-duplicates,return=minimal"):
            raise AssertionError("UNEXPECTED_REQUEST")
        if not isinstance(body, list) or not body:
            raise AssertionError("INVALID_BATCH")
        self.requests.append(len(body))
        fail = len(self.requests) == self.fail_at
        if fail and not self.commit_before_failure:
            raise TimeoutError("SYNTHETIC_PRE_COMMIT_FAILURE")
        for row in body:
            if row["store_id"] != STORE["id"] or not row["first_seen_run_id"]:
                raise AssertionError("INVALID_FIXTURE_ROW")
            self.rows.setdefault(row["review_key"], deepcopy(row))
        if fail:
            raise TimeoutError("SYNTHETIC_RESPONSE_LOST_AFTER_COMMIT")
        return None

    def history(self):
        return deepcopy(list(self.rows.values()))


def rows_for(candidates, run_id):
    return [production.prepare_review_row(r, STORE_MAP, run_id) for r in candidates]


def save(transport, candidates, *, dry_run, run_id):
    # Exercise the actual production save path, with all I/O replaced.
    with patch.object(production, "supabase_request", transport.request), \
         patch.object(production, "load_store_id_map", return_value=STORE_MAP), \
         patch.object(production, "load_existing_reviews", side_effect=AssertionError("UNEXPECTED_HISTORY_FETCH")), \
         contextlib.redirect_stdout(io.StringIO()):
        production.save_reviews(candidates, run_id,
                                existing_reviews=transport.history(),
                                dry_run=dry_run, conservative_dedupe=True)


def expect_failed_batch(transport, rows):
    with patch.object(production, "supabase_request", transport.request):
        try:
            production.upsert_review_batch(rows, batch_size=1)
        except RuntimeError as exc:
            assert "배치 2" in str(exc)
            return
    raise AssertionError("FAILED_BATCH_REPORTED_SUCCESS")


def run_tests():
    from datetime import timedelta
    assert production.now_kst().utcoffset() == timedelta(hours=9)
    old = candidate("Synthetic A", "Historical original review.")
    new = candidate("Synthetic B", "New fixture review.")
    later = candidate("Synthetic C", "Second fixture review.")
    final = candidate("Synthetic D", "Third fixture review.")
    old_row = rows_for([old], 1)[0]
    transport = MemoryReviewTransport([old_row])
    baseline = transport.history()
    save(transport, [old, new], dry_run=True, run_id=2)
    assert transport.history() == baseline and transport.requests == []

    # Existing row + one new row, then replay the identical input.
    save(transport, [old, new], dry_run=False, run_id=2)
    assert len(transport.rows) == 2 and transport.requests == [1]
    assert transport.rows[old_row["review_key"]] == old_row
    first_new_row = deepcopy(transport.rows[production.canonical_review_hash(new)])
    save(transport, [old, new], dry_run=False, run_id=3)
    assert len(transport.rows) == 2 and transport.requests == [1]
    assert transport.rows[first_new_row["review_key"]] == first_new_row

    # A different text by a previously observed author must be held.
    variant = dict(old, text="A changed or translated fixture text.")
    save(transport, [variant], dry_run=False, run_id=4)
    assert transport.requests == [1] and len(transport.rows) == 2

    # A conflict must not update an existing row's rating, text or run metadata.
    conflicting = dict(old_row, rating=1, first_seen_run_id=99)
    with patch.object(production, "supabase_request", transport.request):
        production.upsert_review_batch([conflicting])
    assert transport.rows[old_row["review_key"]] == old_row

    # A failed second request stops the third, whether or not it committed.
    outgoing = rows_for([new, later, final], 5)
    failure = MemoryReviewTransport([old_row], fail_at=2)
    expect_failed_batch(failure, outgoing)
    assert failure.requests == [1, 1] and len(failure.rows) == 2
    assert outgoing[2]["review_key"] not in failure.rows
    assert failure.rows[old_row["review_key"]] == old_row

    lost = MemoryReviewTransport([old_row], fail_at=2, commit_before_failure=True)
    expect_failed_batch(lost, outgoing)
    assert lost.requests == [1, 1] and len(lost.rows) == 3
    assert outgoing[2]["review_key"] not in lost.rows
    # After re-reading history, only the missing third row is appended.
    lost.fail_at = None
    save(lost, [new, later, final], dry_run=False, run_id=6)
    assert lost.requests == [1, 1, 1] and len(lost.rows) == 4
    assert lost.rows[old_row["review_key"]] == old_row
    assert lost.rows[outgoing[1]["review_key"]]["first_seen_run_id"] == 5
    # Exercise the exact local preflight row builder with the offline writer.
    # No real candidate, run ID or transport enters this test.
    scoped_store = dict(STORE, is_active=True)
    fixture = dict(new, google_source_id_hash="a" * 64)
    memory = MemoryReviewTransport([old_row])
    before = memory.history()
    preview, rows = build_append_preview(scoped_store, before, [fixture], production)
    assert preview["write_approved"] is False and len(rows) == 1
    assert rows[0]["first_seen_run_id"] is None
    planned = [dict(row, first_seen_run_id=7) for row in rows]
    with patch.object(production, "supabase_request", memory.request):
        production.upsert_review_batch(planned)
    outcome = reconcile_append_snapshots(before, memory.history(), planned, STORE["id"])
    assert outcome["status"] == "APPEND_SNAPSHOT_MATCHED"
    assert outcome["write_approved"] is False
    replay, replay_rows = build_append_preview(scoped_store, memory.history(), [fixture], production)
    assert replay["legacy_matched"] == 1 and not replay_rows
    assert memory.requests == [1]
    print("APPEND_EXECUTION_QA: " + json.dumps({
        "status": "SYNTHETIC_WRITER_CONTRACT_PASSED",
        "dry_run_no_requests": True, "existing_rows_preserved": True,
        "replay_no_new_rows": True, "prior_author_held": True,
        "conflict_ignored_in_fixture": True, "failed_batch_stops": True,
        "lost_response_reconciliation": True,
        "local_preflight_to_fixture_writer": True,
        "snapshot_row_reconciliation": True,
        "actual_database_compared": False, "database_writes": False,
        "production_write_approved": False,
    }))


if __name__ == "__main__":
    # Block the imported module's network primitive even if the writer is
    # later changed to call it directly. This test is deliberately offline.
    with patch.object(production, "urlopen", side_effect=AssertionError("NETWORK_FORBIDDEN")):
        run_tests()
