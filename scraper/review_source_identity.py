"""Read-only source identity decision engine; no network or persistence."""
from collections import Counter
import re

HASH = re.compile(r"[0-9a-f]{64}")


def valid_hash(value):
    return isinstance(value, str) and bool(HASH.fullmatch(value))


def source_replay_preview(store_id, observed_hashes, history, links):
    """Classify against a hypothetical, previously verified link registry.

    Each link binds one source hash to one historical row in one store.
    Caller must supply a verified registry; this function cannot authorize
    link creation or inserts. An unseen hash is NOT a confirmed new review.
    """
    def blocked(reason):
        return {"status": reason, "write_approved": False, "database_writes": False}
    if not isinstance(store_id, str) or not store_id:
        return blocked("SOURCE_STORE_INVALID")
    row_ids = set()
    for row in history:
        rid = row.get("id")
        if not isinstance(rid, str) or not rid or rid in row_ids or row.get("store_id") != store_id:
            return blocked("SOURCE_HISTORY_INVALID")
        row_ids.add(rid)
    registry, linked_targets = {}, set()
    for link in links:
        source, target = link.get("source_hash"), link.get("review_id")
        if (link.get("store_id") != store_id or not valid_hash(source)
                or not isinstance(target, str) or target not in row_ids
                or source in registry or target in linked_targets):
            return blocked("SOURCE_REGISTRY_CONFLICT")
        registry[source] = target
        linked_targets.add(target)
    # Only validated hashes are used as dictionary keys.
    frequency = Counter(h for h in observed_hashes if valid_hash(h))
    counts = Counter()
    for source in observed_hashes:
        if not valid_hash(source):
            counts["invalid_source_held"] += 1
        elif frequency[source] != 1:
            counts["duplicate_source_held"] += 1
        elif source in registry:
            counts["already_linked_no_insert"] += 1
        else:
            counts["unlinked_requires_legacy_reconciliation"] += 1
    return {"status": "SOURCE_REPLAY_PREVIEW", "observed": len(observed_hashes),
            "counts": dict(counts), "classified": sum(counts.values()),
            "registry_links": len(registry), "identity_verified": False,
            "write_approved": False, "database_writes": False}


def self_test():
    a, b, c = "a"*64, "b"*64, "c"*64
    old = [{"id":"old-1","store_id":"S"},{"id":"old-2","store_id":"S"}]
    link = {"store_id":"S","source_hash":a,"review_id":"old-1"}
    p = source_replay_preview("S",[a,b],old,[link])
    assert p["counts"] == {"already_linked_no_insert":1,"unlinked_requires_legacy_reconciliation":1}
    assert p["classified"] == 2 and p["write_approved"] is False
    assert source_replay_preview("S",[a,b],old,[link]) == p
    p = source_replay_preview("S",[a,a,b,None,[]],old,[link])
    assert p["counts"] == {"duplicate_source_held":2,"unlinked_requires_legacy_reconciliation":1,"invalid_source_held":2}
    assert p["classified"] == 5
    assert source_replay_preview("S",[a],old,[link,dict(link,review_id="old-2")])["status"] == "SOURCE_REGISTRY_CONFLICT"
    assert source_replay_preview("S",[a],old,[link,dict(link,source_hash=b)])["status"] == "SOURCE_REGISTRY_CONFLICT"
    assert source_replay_preview("S",[a],old,[dict(link,store_id="OTHER")])["status"] == "SOURCE_REGISTRY_CONFLICT"
    assert source_replay_preview("S",[a],old,[dict(link,review_id="missing")])["status"] == "SOURCE_REGISTRY_CONFLICT"
    assert source_replay_preview("S",[a],old+[old[0]],[link])["status"] == "SOURCE_HISTORY_INVALID"
    assert source_replay_preview("S",[a],[dict(old[0],store_id="OTHER")],[link])["status"] == "SOURCE_HISTORY_INVALID"
    p = source_replay_preview("S",[a,b,c],old,[])
    assert p["counts"] == {"unlinked_requires_legacy_reconciliation":3}
    assert p["database_writes"] is False and p["identity_verified"] is False
    print("SOURCE_REPLAY_SELF_TEST_PASS: 13 checks")


if __name__ == "__main__":
    self_test()
