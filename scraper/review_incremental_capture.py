"""Pure incremental capture-to-append diagnostic. No browser, DB, or checkpoint writes."""
from collections import Counter
from review_incremental_boundary import preview_boundary, valid_sequence
from review_source_identity import source_replay_preview
from review_incremental_baseline import UUID, valid


def _capture_plan(store, baseline, records, history, links, production, adapter, base, *,
                    newest_verified=False, snapshot_verified=False, context_verified=False,
                    capture_verified=False, pending_attempts=None):
    """Connect ordered DOM records to the existing source and legacy gates.

    Evidence flags are caller assertions. The caller must independently verify
    complete body/original status, snapshot authority, capture and sort state.
    A successful preview is never permission to stop, save, or advance.
    """
    def result(status, **extra):
        return dict(status=status, database_writes=False, write_approved=False,
                    stop_authorized=False, baseline_advance_authorized=False,
                    full_coverage_verified=False, **extra), []
    if not all(x is True for x in (newest_verified,snapshot_verified,context_verified,capture_verified)) or type(pending_attempts) is not int or pending_attempts!=0:
        return result("CAPTURE_EVIDENCE_HELD")
    if (not isinstance(store,dict) or not valid(store.get("id"),UUID)
            or store.get("is_active") is not True or not isinstance(store.get("store_name"),str)
            or not store["store_name"].strip()):
        return result("CAPTURE_STORE_HELD")
    if any(not isinstance(seq,list) or any(not isinstance(r,dict) for r in seq)
           for seq in (records,history,links)) or not 1<=len(records)<=1000:
        return result("CAPTURE_INPUT_INVALID")
    store_id=store["id"]
    ordered=[production.hash_google_source_review_id(store_id,r.get("source_id")) for r in records]
    if not valid_sequence(ordered):
        return result("CAPTURE_ID_SEQUENCE_INVALID")
    registry=source_replay_preview(store_id,ordered,history,links)
    if registry["status"]!="SOURCE_REPLAY_PREVIEW":
        return result("CAPTURE_REGISTRY_HELD",registry_status=registry["status"])
    known={r["source_hash"] for r in links}
    boundary=preview_boundary(store_id,baseline,ordered,known,newest_verified=True,
                              registry_verified=True,context_verified=True)
    if boundary["status"]!="INCREMENTAL_BOUNDARY_CANDIDATE":
        return result("CAPTURE_BOUNDARY_HELD",boundary_status=boundary["status"])
    n=boundary["unlinked_prefix"]
    if n==0:
        return result("CAPTURE_NO_UNLINKED_PREFIX",overlap=boundary["ordered_overlap"],hypothetical_rows=0)
    # Preserve cross-boundary same-author evidence. Linked current records can
    # contain changed author labels not yet reflected in legacy history.
    if any(not isinstance(r.get("author"),str) or not r["author"].strip() for r in records):
        return result("CAPTURE_AUTHOR_HELD",unlinked_prefix=n)
    authors=[production.normalize_spaces(r["author"]).casefold() for r in records]
    counts=Counter(authors)
    if any(not a or a in {"anonymous","unknown"} or counts[a]!=1 for a in authors[:n]):
        return result("CAPTURE_AUTHOR_COLLISION_HELD",unlinked_prefix=n)
    prefix=records[:n]
    # Missing text is not yet proven to be a rating-only review. Do not
    # silently turn it into an empty body or accept a collapsed body.
    if any(r.get("body_scope")!="PRIMARY" or not isinstance(r.get("body"),str)
           or not r["body"].strip() or r.get("body_complete_verified") is not True
           for r in prefix):
        return result("CAPTURE_BODY_HELD",unlinked_prefix=n)
    candidates,gaps=adapter(prefix,store["store_name"],base,production,store_id=store_id)
    if any(gaps.values()) or [r.get("google_source_id_hash") for r in candidates]!=ordered[:n]:
        return result("CAPTURE_ADAPTER_HELD",unlinked_prefix=n)
    from review_append_preflight import build_append_preview
    keys=[production.canonical_review_hash(r) for r in candidates]
    if len(set(keys))!=n:
        return result("CAPTURE_KEY_COLLISION_HELD",unlinked_prefix=n)
    legacy, rows=build_append_preview(store,history,candidates,production)
    # All-or-hold checkpoint preview. Never classify an unresolved legacy
    # match as a safely new ID, or silently discard a rejected prefix record.
    if (len(rows)!=n or {r.get("review_key") for r in rows}!=set(keys)
            or legacy["hypothetical_row_shape_valid"]!=n):
        return result("CAPTURE_LEGACY_HELD",unlinked_prefix=n,
                      hypothetical_rows=len(rows))
    # Bind each candidate to its exact canonical row without relying on
    # the legacy planner's output ordering. Keep the plan in memory only.
    by_key={r["review_key"]:r for r in rows}
    if len(by_key)!=n or any(r.get("store_id")!=store_id or r.get("first_seen_run_id") is not None for r in rows):
        return result("CAPTURE_ROW_MAPPING_HELD",unlinked_prefix=n)
    report,_=result("CAPTURE_APPEND_PREVIEW",unlinked_prefix=n,
                    overlap=boundary["ordered_overlap"],hypothetical_rows=n)
    return report, [(source,dict(by_key[key])) for source,key in zip(ordered[:n],keys)]


def preview_capture(store, baseline, records, history, links, production, adapter, base, *,
                    newest_verified=False, snapshot_verified=False, context_verified=False,
                    capture_verified=False, pending_attempts=None):
    """Public aggregate diagnostic; discard all transient row payloads."""
    report,_=_capture_plan(store,baseline,records,history,links,production,adapter,base,
                           newest_verified=newest_verified,snapshot_verified=snapshot_verified,
                           context_verified=context_verified,capture_verified=capture_verified,
                           pending_attempts=pending_attempts)
    return report


def self_test():
    from datetime import date
    import scraper as production
    from local_review_profile_probe import adapt_local_records
    store=dict(id="10000000-0000-0000-0000-000000000001",store_name="Fixture",
               sv="SV",country="Country",is_active=True)
    sid=store["id"]
    def record(i):
        return dict(source_id=f"fixture-{i}",author=f"Author {i}",rating=5,
                    date_label="2 days ago",body=f"Text {i}",body_scope="PRIMARY",
                    body_complete_verified=True)
    raw=[record(i) for i in range(31)]
    known=[production.hash_google_source_review_id(sid,r["source_id"]) for r in raw[1:]]
    history=[dict(id=f"old-{i}",store_id=sid,store_name="Fixture",author=r["author"],
                  text=r["body"],rating=5,date=r["date_label"],review_key=f"{i:064x}")
             for i,r in enumerate(raw[1:],1)]
    links=[dict(store_id=sid,source_hash=h,review_id=r["id"]) for h,r in zip(known,history)]
    baseline=dict(store_id=sid,committed=True,newest_verified=True,head=known)
    flags=dict(newest_verified=True,snapshot_verified=True,context_verified=True,
               capture_verified=True,pending_attempts=0)
    def check(records=raw, prior=baseline, hist=history, registry=links, **changes):
        p=preview_capture(store,prior,records,hist,registry,production,adapt_local_records,
                          date(2026,11,26),**dict(flags,**changes))
        assert not p["database_writes"] and not p["write_approved"] and not p["baseline_advance_authorized"] and not p["stop_authorized"]
        return p["status"]
    assert check()=="CAPTURE_APPEND_PREVIEW"
    assert check(raw[1:])=="CAPTURE_NO_UNLINKED_PREFIX"
    assert check(raw[:-1])=="CAPTURE_BOUNDARY_HELD"
    assert check(raw+[raw[0]])=="CAPTURE_ID_SEQUENCE_INVALID"
    assert check([dict(raw[0],author=raw[1]["author"])]+raw[1:])=="CAPTURE_AUTHOR_COLLISION_HELD"
    assert check([dict(raw[0],body_complete_verified=False)]+raw[1:])=="CAPTURE_BODY_HELD"
    assert check([dict(raw[0],body_scope="NOT_DETECTED")]+raw[1:])=="CAPTURE_BODY_HELD"
    assert check([dict(raw[0],rating=0)]+raw[1:])=="CAPTURE_ADAPTER_HELD"
    assert check(registry=links+[links[0]])=="CAPTURE_REGISTRY_HELD"
    assert check(pending_attempts=1)=="CAPTURE_EVIDENCE_HELD"
    assert check(snapshot_verified=False)=="CAPTURE_EVIDENCE_HELD"
    assert check(hist=history+[dict(history[0],id="legacy-extra",author=raw[0]["author"],text="old",review_key="f"*64)])=="CAPTURE_LEGACY_HELD"
    print("INCREMENTAL_CAPTURE_SELF_TEST_PASS")


if __name__=="__main__":
    self_test()
