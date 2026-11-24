"""Aggregate-only review source-ID and language-script diagnostics.

Never outputs actual review bodies, Google source IDs, author names, or hashes.
In-memory source hashes are only used to count collisions.
"""
import re


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SCRIPTS = {
    "latin": re.compile(r"[A-Za-z]"),
    "hangul": re.compile(r"[\uAC00-\uD7A3]"),
    "han": re.compile(r"[\u4E00-\u9FFF]"),
    "thai": re.compile(r"[\u0E00-\u0E7F]"),
    "cyrillic": re.compile(r"[\u0400-\u04FF]"),
}


def script_counts(reviews):
    """Independent script flags; a review may contain several writing systems."""
    counts = {"total": len(reviews), "empty": 0, "mixed_hangul_latin": 0}
    counts.update({name: 0 for name in SCRIPTS})
    for review in reviews:
        body = review.get("text") or review.get("review_text") or ""
        if not isinstance(body, str) or not body.strip():
            counts["empty"] += 1
            continue
        present = {name for name, pattern in SCRIPTS.items() if pattern.search(body)}
        for name in present:
            counts[name] += 1
        if "hangul" in present and "latin" in present:
            counts["mixed_hangul_latin"] += 1
    return counts


def source_identity_counts(reviews):
    """Validate 64-char hashed IDs and detect collisions without exporting IDs."""
    seen = {}
    counts = {
        "candidates": len(reviews),
        "hashed_source_ids_valid": 0,
        "hashed_source_ids_missing": 0,
        "hashed_source_ids_invalid": 0,
        "hashed_source_ids_duplicate": 0,
        "source_id_reused_with_distinct_text": 0,
    }
    for review in reviews:
        source_hash = review.get("google_source_id_hash")
        if source_hash is None or source_hash == "":
            counts["hashed_source_ids_missing"] += 1
            continue
        if not isinstance(source_hash, str) or not HASH_PATTERN.fullmatch(source_hash):
            counts["hashed_source_ids_invalid"] += 1
            continue
        counts["hashed_source_ids_valid"] += 1
        body = review.get("text") or ""
        normalized_body = body.strip().casefold() if isinstance(body, str) else ""
        if source_hash in seen:
            counts["hashed_source_ids_duplicate"] += 1
            if seen[source_hash] != normalized_body:
                counts["source_id_reused_with_distinct_text"] += 1
        else:
            seen[source_hash] = normalized_body
    return counts



def reconciliation_blockers(row):
    """Fail-closed, aggregate-only eligibility checks for one read-only store.

    A successful Python execution is not evidence of full Maps feed coverage.
    No raw review data or account identifiers enter the returned issue codes.
    """
    reasons = []
    if row.get("extraction_status") != "SCANNED":
        reasons.append("store_scan_not_completed")
    live = row.get("live_candidates")
    saved = row.get("existing_db_rows")
    if not isinstance(live, int) or live < 0:
        reasons.append("candidate_count_missing")
    elif live == 0:
        reasons.append(
            "historical_store_zero_live_reviews"
            if isinstance(saved, int) and saved > 0 else "zero_review_count_unverified"
        )
    else:
        metrics = row.get("source_id_metrics") or {}
        if (metrics.get("candidates") != live
                or metrics.get("hashed_source_ids_valid") != live
                or metrics.get("hashed_source_ids_missing") != 0
                or metrics.get("hashed_source_ids_invalid") != 0):
            reasons.append("source_review_id_coverage_incomplete")
        if (metrics.get("hashed_source_ids_duplicate") != 0
                or metrics.get("source_id_reused_with_distinct_text") != 0):
            reasons.append("source_review_id_collision")
        if row.get("observed_review_count") != live:
            reasons.append("observed_candidate_count_mismatch")
        if row.get("matching_or_potential_total") != live:
            reasons.append("review_reconciliation_count_mismatch")
    browser = row.get("browser_state") or {}
    if browser.get("signed_in_maps_ui") is not True:
        reasons.append("authenticated_maps_ui_unverified")
    if browser.get("page_category") != "maps_place":
        reasons.append("maps_place_page_unverified")
    if row.get("completeness_verified") is not True:
        reasons.append("full_feed_coverage_unverified")
    return reasons


def reconciliation_verdict(rows, expected_countries):
    """PASS only if every expected country has *fully verified* coverage."""
    seen = set()
    blockers = {}
    for row in rows:
        country = row.get("country")
        if not isinstance(country, str) or country not in expected_countries or country in seen:
            blockers.setdefault("scope", []).append("duplicate_or_unknown_country")
            continue
        seen.add(country)
        blockers[country] = reconciliation_blockers(row)
    for country in expected_countries:
        if country not in seen:
            blockers[country] = ["store_not_scanned"]
    return {
        "status": "PARTIAL" if any(blockers.values()) else "PASS",
        "store_gate_reasons": blockers,
        # This diagnostic never grants permission to insert into production.
        "database_writes_approved": False,
    }


def should_retry_read_only_store(saved_count, candidate_count, attempt_number, max_attempts=2):
    """A bounded retry is justified for an established store with zero cards.

    Each attempt must use an independent tab in the same authenticated context.
    The audit never combines candidates from different attempts.
    """
    return (
        isinstance(saved_count, int) and not isinstance(saved_count, bool)
        and saved_count > 0
        and isinstance(attempt_number, int) and 1 <= attempt_number < max_attempts
        and (candidate_count is None or candidate_count == 0)
    )
