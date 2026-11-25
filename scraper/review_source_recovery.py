"""Pure recovery classification for uncertain source-aware append outcomes.

No I/O, retries, production credentials, or authorization. A caller must
obtain a fresh authoritative transaction snapshot before invoking this module.
"""
import re

HASH = re.compile(r"[0-9a-f]{64}")


def valid_hash(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def classify_recovery(store_id, attempted, rows, links, *, snapshot_verified=False):
    """Return aggregate decisions; never release an insert or change old data.

    attempted contains source_hash, review_id, review_key and store_id from
    the exact attempted transaction. rows and links must represent the same
    authoritative snapshot, not a partially visible browser read.
    """
    def result(status, **extra):
        return dict(status=status, retry_authorized=False, write_approved=False,
                    database_writes=False, **extra)
    if snapshot_verified is not True:
        return result("RECOVERY_SNAPSHOT_UNVERIFIED")
    if not isinstance(store_id, str) or not store_id or not attempted:
        return result("RECOVERY_INPUT_INVALID")
    if any(not isinstance(x, dict) for seq in (attempted, rows, links) for x in seq):
        return result("RECOVERY_INPUT_INVALID")
    def valid_text(v):
        return isinstance(v, str) and bool(v.strip())
    by_id, by_key, by_source, by_target = {}, {}, {}, {}
    for row in rows:
        rid, key = row.get("id"), row.get("review_key")
        if (row.get("store_id") != store_id or not valid_text(rid)
                or not valid_text(key) or rid in by_id or key in by_key):
            return result("RECOVERY_HISTORY_INVALID")
        by_id[rid], by_key[key] = row, row
    for link in links:
        source, rid = link.get("source_hash"), link.get("review_id")
        if (link.get("store_id") != store_id or not valid_hash(source)
                or not valid_text(rid) or rid not in by_id
                or source in by_source or rid in by_target):
            return result("RECOVERY_REGISTRY_INVALID")
        by_source[source], by_target[rid] = rid, source
    seen_sources, seen_ids, seen_keys = set(), set(), set()
    counts = dict(committed_confirmed=0, absent_replan_required=0, conflict_held=0)
    for item in attempted:
        source, rid, key = (item.get(k) for k in ("source_hash", "review_id", "review_key"))
        if (item.get("store_id") != store_id or not valid_hash(source)
                or not valid_text(rid) or not valid_text(key)
                or source in seen_sources or rid in seen_ids or key in seen_keys):
            return result("RECOVERY_ATTEMPT_INVALID")
        seen_sources.add(source)
        seen_ids.add(rid)
        seen_keys.add(key)
        if by_source.get(source) == rid and by_id[rid]["review_key"] == key:
            counts["committed_confirmed"] += 1
        elif source in by_source or rid in by_id or key in by_key:
            counts["conflict_held"] += 1
        else:
            counts["absent_replan_required"] += 1
    status = ("RECOVERY_CONFLICT_HELD" if counts["conflict_held"] else
              "RECOVERY_FRESH_PLAN_REQUIRED" if counts["absent_replan_required"] else
              "RECOVERY_COMMIT_CONFIRMED")
    return result(status, attempted=len(attempted), classified=sum(counts.values()), counts=counts)


def self_test():
    from copy import deepcopy
    a, b = "a"*64, "b"*64
    old = dict(id="old",store_id="S",review_key="old-key",text="preserved")
    attempted = [dict(store_id="S",source_hash=a,review_id="new",review_key="new-key")]
    new = dict(id="new",store_id="S",review_key="new-key",text="first")
    link = dict(store_id="S",source_hash=a,review_id="new")
    rows, links = [old,new], [link]
    baseline = deepcopy((attempted,rows,links))
    def check(r,l,items=attempted,verified=True):
        p = classify_recovery("S",items,r,l,snapshot_verified=verified)
        assert p["write_approved"] is False and p["retry_authorized"] is False
        return p
    assert check(rows,links,verified=False)["status"] == "RECOVERY_SNAPSHOT_UNVERIFIED"
    assert check(rows,links)["status"] == "RECOVERY_COMMIT_CONFIRMED"
    assert check([old],[])["status"] == "RECOVERY_FRESH_PLAN_REQUIRED"
    assert check(rows,[])["status"] == "RECOVERY_CONFLICT_HELD"
    assert check([old],[link])["status"] == "RECOVERY_REGISTRY_INVALID"
    assert check(rows,[dict(link,review_id="old")])["status"] == "RECOVERY_CONFLICT_HELD"
    assert check(rows,[dict(link,source_hash=b)])["status"] == "RECOVERY_CONFLICT_HELD"
    assert check([old,dict(new,id="other")],[])["status"] == "RECOVERY_CONFLICT_HELD"
    assert check([old,dict(new,review_key="other-key")],links)["status"] == "RECOVERY_CONFLICT_HELD"
    assert check(rows,[link,link])["status"] == "RECOVERY_REGISTRY_INVALID"
    assert check(rows,[dict(link,store_id="T")])["status"] == "RECOVERY_REGISTRY_INVALID"
    assert check(rows+[old],links)["status"] == "RECOVERY_HISTORY_INVALID"
    assert check(rows,links,attempted*2)["status"] == "RECOVERY_ATTEMPT_INVALID"
    p = check(rows,links,attempted+[dict(store_id="S",source_hash=b,review_id="later",review_key="later-key")])
    assert p["counts"] == dict(committed_confirmed=1,absent_replan_required=1,conflict_held=0)
    assert p["classified"] == p["attempted"] == 2
    assert (attempted,rows,links) == baseline
    print("SOURCE_RECOVERY_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
