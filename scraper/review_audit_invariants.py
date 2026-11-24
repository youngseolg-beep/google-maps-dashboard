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
    print("AUDIT_INVARIANTS_SELF_TEST_PASS: 16 checks")


if __name__ == "__main__":
    self_test()
