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
