"""Read-only incremental boundary preview; never authorizes stopping or writes."""
import re

HASH = re.compile(r"[0-9a-f]{64}")
MIN_OVERLAP = 30
MAX_WINDOW = 10000  # Same hard bound as the live Maps scan.


def valid_sequence(values):
    return (isinstance(values, list) and len(values) <= MAX_WINDOW
            and all(isinstance(v, str) and HASH.fullmatch(v) for v in values)
            and len(set(values)) == len(values))


def observed_frontier_reached(head, observed):
    """Ordered observation overlap only; makes no persistence/completeness claim."""
    if not valid_sequence(head) or len(head)!=MIN_OVERLAP or not valid_sequence(observed) or head[0] not in observed:
        return False
    position=observed.index(head[0])
    return (not set(head).intersection(observed[:position])
            and observed[position:position+MIN_OVERLAP]==head)


def preview_boundary(store_id, baseline, observed, known, *, newest_verified=False,
                     registry_verified=False, context_verified=False):
    """Require an exact ordered overlap with the previous committed head.

    Verification flags are caller assertions, not evidence acquired here.
    Known IDs must come from a verified same-store registry. No review
    content, source IDs or candidate payloads are returned in the report.
    """
    def result(status, **extra):
        return dict(status=status, stop_authorized=False, write_approved=False,
                    full_coverage_verified=False, database_writes=False, **extra)
    if not all(x is True for x in (newest_verified, registry_verified, context_verified)):
        return result("INCREMENTAL_EVIDENCE_UNVERIFIED")
    if (not isinstance(store_id, str) or not store_id or not isinstance(baseline, dict)
            or baseline.get("store_id") != store_id or baseline.get("committed") is not True
            or baseline.get("newest_verified") is not True):
        return result("INCREMENTAL_BASELINE_REQUIRED")
    prior = baseline.get("head")
    if not valid_sequence(prior) or len(prior) < MIN_OVERLAP:
        return result("INCREMENTAL_BASELINE_INVALID")
    if not valid_sequence(observed):
        return result("INCREMENTAL_OBSERVATION_INVALID")
    if (not isinstance(known, (set, frozenset)) or len(known) > 100000
            or any(not isinstance(v, str) or not HASH.fullmatch(v) for v in known)
            or not set(prior).issubset(known)):
        return result("INCREMENTAL_REGISTRY_INVALID")
    if prior[0] not in observed:
        return result("INCREMENTAL_ANCHOR_NOT_OBSERVED", observed=len(observed))
    index = observed.index(prior[0])
    prefix, tail = observed[:index], observed[index:]
    # A previous partial run can already have committed part of the prefix.
    # Its receipt does not replace the last complete boundary.
    if set(prefix).intersection(prior):
        return result("INCREMENTAL_ORDER_CONFLICT")
    common = min(len(tail), len(prior))
    if tail[:common] != prior[:common] or any(h not in known for h in tail):
        return result("INCREMENTAL_ORDER_CONFLICT")
    if common < MIN_OVERLAP:
        return result("INCREMENTAL_OVERLAP_INSUFFICIENT", overlap=common)
    return result("INCREMENTAL_BOUNDARY_CANDIDATE", observed=len(observed),
                  unlinked_prefix=len(prefix), ordered_overlap=common,
                  historical_coverage_verified=False)


def self_test():
    prior = [f"{i:064x}" for i in range(1, 41)]
    fresh = [f"{i:064x}" for i in range(101, 104)]
    baseline = dict(store_id="S", head=prior, committed=True, newest_verified=True)
    flags = dict(newest_verified=True, registry_verified=True, context_verified=True)
    known = set(prior)
    def check(obs, base=baseline, registry=known, **overrides):
        report = preview_boundary("S", base, obs, registry, **dict(flags, **overrides))
        assert not report["stop_authorized"] and not report["write_approved"]
        return report
    p = check(fresh + prior[:30])
    assert p["status"] == "INCREMENTAL_BOUNDARY_CANDIDATE" and p["unlinked_prefix"] == 3
    assert check(prior[:30])["unlinked_prefix"] == 0
    assert check(fresh + prior[:29])["status"] == "INCREMENTAL_OVERLAP_INSUFFICIENT"
    assert check(fresh)["status"] == "INCREMENTAL_ANCHOR_NOT_OBSERVED"
    assert check(fresh + prior[:10] + [fresh[0]])["status"] == "INCREMENTAL_OBSERVATION_INVALID"
    assert check(fresh + prior[:10] + prior[11:31])["status"] == "INCREMENTAL_ORDER_CONFLICT"
    assert check([prior[-1]] + prior[:30])["status"] == "INCREMENTAL_ORDER_CONFLICT"
    assert check(fresh + prior + ["f"*64])["status"] == "INCREMENTAL_ORDER_CONFLICT"
    assert check(prior[:30], dict(baseline, store_id="T"))["status"] == "INCREMENTAL_BASELINE_REQUIRED"
    assert check(prior[:30], dict(baseline, committed=False))["status"] == "INCREMENTAL_BASELINE_REQUIRED"
    assert check(prior[:30], dict(baseline, head=prior[:20]))["status"] == "INCREMENTAL_BASELINE_INVALID"
    assert check(prior[:30], registry=set(prior[:-1]))["status"] == "INCREMENTAL_REGISTRY_INVALID"
    for flag in flags:
        assert check(prior[:30], **{flag:False})["status"] == "INCREMENTAL_EVIDENCE_UNVERIFIED"
    print("INCREMENTAL_BOUNDARY_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
