"""Pure reconciliation invariants, with no browser or database access."""


def candidate_partition_ok(observed, adapted, unique, matched, ready, held, gaps):
    """Do not silently accept losses in adaptation or legacy key merging."""
    values = (observed, adapted, unique, matched, ready, held)
    return (all(type(n) is int and n >= 0 for n in values)
            and observed > 0 and observed == adapted == unique
            and matched + ready + held == unique
            and not any(gaps.values()))


def preview_partition_ok(report):
    """Verify the second, more conservative append-preview partition."""
    fields = ("candidate_count", "valid_candidate_count", "legacy_unique_candidates",
              "legacy_matched", "legacy_held", "additional_held",
              "hypothetical_row_shape_valid", "row_shape_errors")
    values = [report.get(k) for k in fields]
    if not all(type(n) is int and n >= 0 for n in values):
        return False
    total, accepted, unique, matched, legacy_held, extra_held, ready, errors = values
    return (total > 0 and total == accepted == unique
            and matched + legacy_held + extra_held + ready + errors == unique
            and errors == 0 and not any(report.get("blocking_reasons", {}).values())
            and report.get("write_approved") is False
            and report.get("database_writes") is False)


def diagnostic_partition(observed, adapted, gaps, preview):
    """Account for every observed card, including rejected/held candidates.

    This is a count invariant only. A balanced diagnostic is never write approval.
    """
    names = ("candidate_count", "valid_candidate_count", "legacy_unique_candidates",
             "legacy_matched", "legacy_held", "additional_held",
             "hypothetical_row_shape_valid", "row_shape_errors")
    counts = [preview.get(k) for k in names]
    if not isinstance(gaps, dict) or not all(type(n) is int and n >= 0
            for n in [observed, adapted, *counts, *gaps.values()]):
        return {"status": "PARTITION_INVALID", "write_approved": False}
    total, valid, unique, matched, legacy_held, extra_held, ready, errors = counts
    categories = {
        "adaptation_held": sum(gaps.values()),
        "preflight_rejected": total - valid,
        "legacy_key_collapsed": valid - unique,
        "matched_existing": matched,
        "held_by_planner": legacy_held + extra_held,
        "potential_new_unapproved": ready,
        "row_shape_errors": errors,
    }
    balanced = (observed > 0 and adapted == total and observed == adapted + categories["adaptation_held"]
                and total >= valid >= unique
                and unique == matched + legacy_held + extra_held + ready + errors
                and sum(categories.values()) == observed
                and preview.get("database_writes") is False and preview.get("write_approved") is False)
    return {"status": "PARTITION_BALANCED" if balanced else "PARTITION_INVALID",
            "observed": observed, "categories": categories,
            "classified_total": sum(categories.values()), "write_approved": False}


def self_test():
    assert candidate_partition_ok(8, 8, 8, 5, 2, 1, {})
    assert not candidate_partition_ok(8, 7, 7, 5, 1, 1, {})
    assert not candidate_partition_ok(8, 8, 7, 5, 1, 1, {})
    assert not candidate_partition_ok(8, 8, 8, 5, 1, 1, {})
    assert not candidate_partition_ok(8, 8, 8, 5, 2, 1, {"bad": 1})
    assert not candidate_partition_ok(0, 0, 0, 0, 0, 0, {})
    assert not candidate_partition_ok(8, 8, 8, 9, 0, -1, {})
    assert not candidate_partition_ok(1, 1, 1, True, 0, 0, {})
    p = dict(candidate_count=8, valid_candidate_count=8, legacy_unique_candidates=8,
             legacy_matched=5, legacy_held=1, additional_held=0,
             hypothetical_row_shape_valid=2, row_shape_errors=0,
             blocking_reasons={}, write_approved=False, database_writes=False)
    assert preview_partition_ok(p)
    assert not preview_partition_ok(dict(p, legacy_unique_candidates=7))
    assert not preview_partition_ok(dict(p, hypothetical_row_shape_valid=1))
    assert not preview_partition_ok(dict(p, hypothetical_row_shape_valid=1, row_shape_errors=1))
    assert not preview_partition_ok(dict(p, blocking_reasons={"store_scope_blocked": 1}))
    assert not preview_partition_ok(dict(p, write_approved=True))
    assert not preview_partition_ok(dict(p, database_writes=True))
    assert not preview_partition_ok({})
    assert diagnostic_partition(8, 8, {}, p)["status"] == "PARTITION_BALANCED"
    partial = diagnostic_partition(10, 8, {"unverified_body_scope": 2}, p)
    assert partial["status"] == "PARTITION_BALANCED" and partial["categories"]["adaptation_held"] == 2
    assert partial["classified_total"] == 10 and partial["write_approved"] is False
    assert diagnostic_partition(10, 8, {"unverified_body_scope": 1}, p)["status"] == "PARTITION_INVALID"
    assert diagnostic_partition(8, 8, {}, dict(p, hypothetical_row_shape_valid=3))["status"] == "PARTITION_INVALID"
    assert diagnostic_partition(8, 8, {}, dict(p, write_approved=True))["status"] == "PARTITION_INVALID"
    assert diagnostic_partition(8, 8, {}, dict(p, valid_candidate_count=7))["status"] == "PARTITION_INVALID"
    rejected = dict(p, valid_candidate_count=7, legacy_unique_candidates=6,
                    legacy_matched=3, legacy_held=1, hypothetical_row_shape_valid=2)
    r = diagnostic_partition(8, 8, {}, rejected)
    assert r["status"] == "PARTITION_BALANCED" and r["categories"]["preflight_rejected"] == 1 and r["categories"]["legacy_key_collapsed"] == 1
    assert diagnostic_partition(8, 8, {"bad": True}, p)["status"] == "PARTITION_INVALID"
    print("AUDIT_INVARIANTS_SELF_TEST_PASS: 25 checks")


if __name__ == "__main__":
    self_test()
