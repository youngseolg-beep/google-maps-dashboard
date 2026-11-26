"""Read-only legacy linkage evidence; never confirms identity or writes a link."""
from collections import Counter, defaultdict
from review_source_identity import source_replay_preview, valid_hash


def reconcile_preview(store_id, records, history, links, production):
    """Conservatively partition every raw observation before adaptation.

    The returned aggregates are proposals only. Exact text/author/rating
    does not prove a Google identity. Never infer that absent text means
    a rating-only review. Do not output source IDs, hashes or row IDs.
    """
    def held(status):
        return dict(status=status, database_writes=False, write_approved=False,
                    identity_verified=False, links_persisted=0)
    if (not isinstance(store_id,str) or not store_id
            or any(not isinstance(seq,list) or any(not isinstance(r,dict) for r in seq)
                   for seq in (records,history,links))):
        return held("RECONCILE_INPUT_INVALID")
    sources=[production.hash_google_source_review_id(store_id,r.get("source_id")) for r in records]
    gate=source_replay_preview(store_id,sources,history,links)
    if gate["status"]!="SOURCE_REPLAY_PREVIEW":
        return held("RECONCILE_REGISTRY_HELD")
    def norm(v):
        return production.normalize_spaces(v).casefold() if isinstance(v,str) else ""
    def signature(author,rating,body):
        a,b=norm(author),norm(body)
        if not a or a in {"anonymous","unknown"} or type(rating) is not int or not 1<=rating<=5 or not b:
            return None
        return a,rating,b
    by_signature=defaultdict(list)
    by_author=defaultdict(list)
    for row in history:
        a=norm(row.get("author"))
        if a:
            by_author[a].append(row["id"])
        sig=signature(row.get("author"),row.get("rating"),row.get("text"))
        if sig:
            by_signature[sig].append(row["id"])
    registry={r["source_hash"]:r["review_id"] for r in links}
    owners=set(registry.values())
    frequency=Counter(h for h in sources if valid_hash(h))
    signatures=[signature(r.get("author"),r.get("rating"),r.get("body"))
                if r.get("body_scope")=="PRIMARY" else None for r in records]
    sig_counts=Counter(x for x in signatures if x is not None)
    authors=Counter(norm(r.get("author")) for r in records)
    counts=Counter()
    for raw,h,sig in zip(records,sources,signatures):
        a=norm(raw.get("author"))
        if not valid_hash(h):
            category="invalid_source_held"
        elif frequency[h]!=1:
            category="duplicate_source_held"
        elif h in registry:
            category="already_linked_no_insert"
        elif not a or a in {"anonymous","unknown"} or type(raw.get("rating")) is not int or not 1<=raw["rating"]<=5:
            category="metadata_held"
        elif sig is None:
            category="body_unverified_held"
        elif sig_counts[sig]!=1:
            category="shared_live_signature_held"
        elif len(by_signature[sig])>1:
            category="multiple_historical_targets_held"
        elif len(by_signature[sig])==1:
            target=by_signature[sig][0]
            category="target_already_linked_held" if target in owners else "exact_linkage_proposal_unapproved"
        elif a in by_author:
            category="prior_author_collision_held"
        elif authors[a]!=1:
            category="live_author_collision_held"
        else:
            category="potential_new_unapproved"
        counts[category]+=1
    return dict(status="RECONCILE_CLASSIFIED", observed=len(records),
                classified=sum(counts.values()), balanced=sum(counts.values())==len(records),
                counts=dict(counts), identity_verified=False, links_persisted=0,
                database_writes=False, write_approved=False,
                full_text_verified=False, historical_coverage_verified=False)


def self_test():
    import scraper as production
    store="fixture-store"
    def rec(i,author,body="text",**kw):
        return dict(source_id=str(i),author=author,body=body,rating=5,
                    body_scope="PRIMARY",**kw)
    def saved(i,author,text="text"):
        return dict(id=str(i),store_id=store,author=author,text=text,rating=5)
    a,b,c,d=rec(1,"A"),rec(2,"B"),rec(3,"C"),rec(4,"D")
    history=[saved(1,"A"),saved(2,"B","different")]
    def check(records,rows=history,links=None):
        p=reconcile_preview(store,records,rows,links or [],production)
        assert not p["write_approved"] and not p["database_writes"] and not p["identity_verified"]
        assert p["balanced"] and p["classified"]==len(records)
        return p["counts"]
    assert check([a,b,c,dict(d,body_scope="NOT_DETECTED")])=={
        "exact_linkage_proposal_unapproved":1,"prior_author_collision_held":1,
        "potential_new_unapproved":1,"body_unverified_held":1}
    assert check([a,dict(a,source_id="other")])=={"shared_live_signature_held":2}
    assert check([a],history+[saved(3,"A")])=={"multiple_historical_targets_held":1}
    link=dict(store_id=store,source_hash=production.hash_google_source_review_id(store,"1"),review_id="1")
    assert check([a],links=[link])=={"already_linked_no_insert":1}
    assert check([dict(a,source_id="other")],links=[link])=={"target_already_linked_held":1}
    assert check([c,dict(c,source_id="other",body="different")])=={"live_author_collision_held":2}
    assert check([a,a])=={"duplicate_source_held":2}
    assert check([dict(c,source_id=None)])=={"invalid_source_held":1}
    assert check([dict(c,rating=0)])=={"metadata_held":1}
    assert check([dict(c,body="")])=={"body_unverified_held":1}
    assert reconcile_preview(store,[a],history,[dict(link,store_id="other")],production)["status"]=="RECONCILE_REGISTRY_HELD"
    print("SOURCE_RECONCILE_SELF_TEST_PASS")


if __name__=="__main__":
    self_test()
