"""Pure append-only snapshot checks. Never sends requests or writes to a DB."""


def index_rows(rows, store_id):
    indexed = {}
    for row in rows:
        key = row.get("review_key")
        if not isinstance(key, str) or not key or key in indexed:
            raise ValueError("SNAPSHOT_KEY_INVALID_OR_DUPLICATE")
        if row.get("store_id") != store_id:
            raise ValueError("SNAPSHOT_STORE_MISMATCH")
        indexed[key] = row
    return indexed


def reconcile_append_snapshots(before, after, planned, store_id):
    """Check same-scope snapshots; never treat counts alone as proof of success.

    Snapshots must use identical field selections and a trusted full scope.
    Caller must separately prove visibility, snapshot consistency and exclusivity.
    No row data or keys are returned.
    """
    try:
        if not store_id:
            raise ValueError("SNAPSHOT_STORE_MISSING")
        old = index_rows(before, store_id)
        new = index_rows(after, store_id)
        wanted = index_rows(planned, store_id)
        if set(old) & set(wanted):
            raise ValueError("PLANNED_KEY_ALREADY_PRESENT")
    except ValueError as exc:
        return {"status": "SNAPSHOT_INVALID", "reason": str(exc),
                "database_writes": False, "write_approved": False}
    missing_old = set(old) - set(new)
    changed_old = sum(old[k] != new[k] for k in set(old) & set(new))
    added = set(new) - set(old)
    missing_planned = set(wanted) - added
    unexpected = added - set(wanted)
    changed_new = sum(any(new[k].get(field) != value for field, value in wanted[k].items())
                      for k in added & set(wanted))
    consistent = not (missing_old or changed_old or missing_planned or unexpected or changed_new)
    return {
        "status": "APPEND_SNAPSHOT_MATCHED" if consistent else "APPEND_SNAPSHOT_GAPS",
        "before_count": len(old), "after_count": len(new),
        "planned_count": len(wanted), "added_count": len(added),
        "missing_existing": len(missing_old), "changed_existing": changed_old,
        "missing_planned": len(missing_planned), "unexpected_added": len(unexpected),
        "new_payload_mismatch": changed_new,
        "snapshot_scope_verified": False, "transactional_snapshot_verified": False,
        "database_writes": False, "write_approved": False,
    }


def self_test():
    old = {"review_key": "old", "store_id": "fixture", "rating": 5, "id": 1}
    planned = {"review_key": "new", "store_id": "fixture", "rating": 4}
    new = dict(planned, id=2)
    check = lambda before, after, plan: reconcile_append_snapshots(before, after, plan, "fixture")
    assert check([old], [old, new], [planned])["status"] == "APPEND_SNAPSHOT_MATCHED"
    assert check([old, new], [old, new], [])["status"] == "APPEND_SNAPSHOT_MATCHED"
    assert check([old], [new], [planned])["missing_existing"] == 1
    assert check([old], [dict(old, rating=1), new], [planned])["changed_existing"] == 1
    assert check([old], [old], [planned])["missing_planned"] == 1
    assert check([old], [old, new], [])["unexpected_added"] == 1
    assert check([old], [old, dict(new, rating=2)], [planned])["new_payload_mismatch"] == 1
    assert check([old, old], [old], [])["status"] == "SNAPSHOT_INVALID"
    assert check([old], [old, dict(new, store_id="wrong")], [planned])["status"] == "SNAPSHOT_INVALID"
    assert check([old], [old], [old])["status"] == "SNAPSHOT_INVALID"
    assert check([old], [old, new], [planned])["write_approved"] is False
    print("APPEND_SNAPSHOT_SELF_TEST_PASS: 11 checks")


if __name__ == "__main__":
    self_test()
