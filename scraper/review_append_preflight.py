"""Pure, aggregate-only append preview for the local review diagnostics.

This module never sends requests, writes rows, or authorizes production writes.
The legacy planner/row builder is reused to expose compatibility gaps before
final manual QA. Sample coverage and UI text are not complete review evidence.
"""
from collections import Counter
from datetime import date
import re


def build_append_preview(store, history, candidates, production):
    """Return aggregate report and transient hypothetical rows; never write."""
    reasons = Counter()
    store_id = store.get("id")
    name = store.get("store_name")
    sv = store.get("sv")
    country = store.get("country")
    if not store_id or not all(isinstance(v, str) and v.strip() for v in (name, sv, country)):
        reasons["store_metadata_missing"] += 1
    if store.get("is_active") is not True:
        reasons["store_not_active"] += 1
    if any(row.get("store_id") != store_id for row in history):
        reasons["history_store_mismatch"] += 1

    accepted = []
    source_counts = Counter(r.get("google_source_id_hash") for r in candidates)
    key_counts = Counter(production.make_review_key(r) for r in candidates)
    authors = Counter(production.normalize_spaces(r.get("author") or "").casefold()
                      for r in candidates)
    stored_hashes = {r.get("review_key") for r in history if r.get("review_key")}
    for candidate in candidates:
        source = candidate.get("google_source_id_hash")
        author = production.normalize_spaces(candidate.get("author") or "").casefold()
        rating = candidate.get("rating")
        text = candidate.get("text")
        key = production.make_review_key(candidate)
        issue = None
        if candidate.get("store_name") != name:
            issue = "candidate_store_mismatch"
        elif not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{64}", source):
            issue = "source_id_invalid"
        elif source_counts[source] != 1:
            issue = "duplicate_source_id"
        elif not key or key_counts[key] != 1:
            issue = "legacy_key_collision"
        elif not author or author in {"anonymous", "unknown"}:
            issue = "author_unverified"
        elif type(rating) is not int or not 1 <= rating <= 5:
            issue = "rating_unverified"
        elif not isinstance(text, str) or bool(text.strip()) != candidate.get("has_text"):
            issue = "body_shape_invalid"
        elif not isinstance(candidate.get("date"), str) or not candidate["date"].strip():
            issue = "date_label_missing"
        else:
            try:
                parsed = date.fromisoformat(candidate["review_date"])
                collected = date.fromisoformat(candidate["collected_at"])
                if parsed > collected or candidate.get("review_date_source") not in {"estimated", "displayed"}:
                    issue = "date_unverified"
            except (ValueError, TypeError, KeyError):
                issue = "date_unverified"
        if issue:
            reasons[issue] += 1
            continue
        accepted.append(candidate)

    # Preserve store scope and reuse the conservative production planner.
    scoped_history = [dict(row, store_name=name, text=row.get("text") or "")
                      for row in history if row.get("store_id") == store_id]
    plan = production.plan_safe_review_append(scoped_history, accepted)
    hypothetical = 0
    preview_rows = []
    store_blocked = any(reasons[k] for k in ("store_metadata_missing", "store_not_active", "history_store_mismatch"))
    held = 0
    row_shape_errors = 0
    for candidate in plan["ready"]:
        if store_blocked:
            reasons["store_scope_blocked"] += 1
            held += 1
            continue
        author = production.normalize_spaces(candidate["author"]).casefold()
        if authors[author] != 1:
            reasons["same_author_in_current_sample"] += 1
            held += 1
            continue
        if production.canonical_review_hash(candidate) in stored_hashes:
            reasons["stored_key_collision"] += 1
            held += 1
            continue
        if not store_id or not name or not sv or not country:
            reasons["row_store_metadata_missing"] += 1
            held += 1
            continue
        try:
            # Preview only: no real crawl_run exists. These rows are discarded.
            review = dict(candidate, sv=sv, country=country, city=store.get("city") or "")
            row = production.prepare_review_row(
                review, {production.normalize_store_lookup_key(name): store_id}, None
            )
            if (row["store_id"] != store_id or row["store_name"] != name
                    or row["review_key"] != production.canonical_review_hash(candidate)
                    or row["first_seen_run_id"] is not None):
                raise ValueError("PREVIEW_ROW_INVALID")
            hypothetical += 1
            preview_rows.append(row)
        except (ValueError, TypeError, KeyError, RuntimeError):
            row_shape_errors += 1
            reasons["row_shape_invalid"] += 1
    report = {
        "candidate_count": len(candidates),
        "valid_candidate_count": len(accepted),
        "legacy_matched": plan["already_matched"],
        "legacy_held": len(plan["held"]),
        "legacy_held_reasons": plan["held_reasons"],
        "additional_held": held,
        "hypothetical_row_shape_valid": hypothetical,
        "row_shape_errors": row_shape_errors,
        "blocking_reasons": dict(reasons),
        "hard_gates": ["FULL_TEXT_AND_ORIGINAL_STATUS_UNVERIFIED",
                       "COMPLETE_STORE_COVERAGE_UNVERIFIED",
                       "TRANSACTIONAL_HISTORY_UNVERIFIED",
                       "PRODUCTION_MANUAL_QA_PENDING",
                       "REAL_CRAWL_RUN_NOT_CREATED"],
        "actual_insert_count": 0,
        "database_writes": False,
        "write_approved": False,
    }
    return report, preview_rows


def preview_append(store, history, candidates, production):
    report, _ = build_append_preview(store, history, candidates, production)
    return report


def self_test():
    import scraper as production
    store = dict(id="synthetic-store", store_name="Fixture", sv="Fixture SV",
                 country="Fixture country", is_active=True)
    first = dict(store_name="Fixture", author="Synthetic A", rating=5,
                 text="Synthetic review.", has_text=True, date="2 days ago",
                 review_date="2026-11-22", review_date_source="estimated",
                 collected_at="2026-11-24", google_source_id_hash="a" * 64)
    second = dict(first, author="Synthetic B", google_source_id_hash="b" * 64)
    report = preview_append(store, [], [first, second], production)
    assert report["hypothetical_row_shape_valid"] == 2
    assert report["actual_insert_count"] == 0 and report["write_approved"] is False
    history = [dict(first, store_id=store["id"],
                    review_key=production.canonical_review_hash(first))]
    report = preview_append(store, history, [first, second], production)
    assert report["legacy_matched"] == 1
    assert report["hypothetical_row_shape_valid"] == 1
    report = preview_append(store, [], [first, dict(second, google_source_id_hash="a" * 64)], production)
    assert report["blocking_reasons"]["duplicate_source_id"] == 2
    report = preview_append(store, [], [first, dict(second, author=first["author"], text="Different text.")], production)
    assert report["additional_held"] == 2
    report = preview_append(store, [], [dict(first, rating=0)], production)
    assert report["blocking_reasons"]["rating_unverified"] == 1
    report = preview_append(store, [], [dict(first, review_date="2027-01-01")], production)
    assert report["blocking_reasons"]["date_unverified"] == 1
    report = preview_append(store, [dict(history[0], store_id="wrong")], [second], production)
    assert report["blocking_reasons"]["history_store_mismatch"] == 1
    report = preview_append(dict(store, is_active=False), [], [first], production)
    assert report["blocking_reasons"]["store_not_active"] == 1
    assert report["hypothetical_row_shape_valid"] == 0
    _, rows = build_append_preview(store, history, [first, second], production)
    assert len(rows) == 1 and rows[0]["first_seen_run_id"] is None
    assert report["write_approved"] is False
    print("APPEND_PREFLIGHT_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
