"""Source-aware, in-memory append/replay QA. Never performs database writes."""
from collections import Counter
from review_source_identity import source_replay_preview, valid_hash
from review_append_preflight import build_append_preview


def source_aware_preview(store, history, candidates, links, production):
    """A verified source link takes priority over mutable legacy review text.

    The legacy planner remains mandatory for unlinked IDs. No links are created
    by this function. The caller-visible counts are not permission to write.
    """
    def held(status):
        return {"status":status,"database_writes":False,"write_approved":False}, []
    if (not isinstance(store,dict) or
            any(not isinstance(seq,list) or any(not isinstance(r,dict) for r in seq)
                for seq in (history,candidates,links))):
        return held("SOURCE_APPEND_INPUT_INVALID")
    # Reject malformed text before invoking legacy normalizers/hash builders.
    # Invalid source IDs themselves remain classified by the source gate.
    if any(not isinstance(r.get(k),str) for r in candidates
           for k in ("store_name","author","text")):
        return held("SOURCE_APPEND_INPUT_INVALID")
    store_id = store.get("id")
    hashes = [r.get("google_source_id_hash") for r in candidates]
    report = source_replay_preview(store_id, hashes, history, links)
    if report["status"] != "SOURCE_REPLAY_PREVIEW" or store.get("is_active") is not True:
        return {"status": "SOURCE_APPEND_BLOCKED", "source_gate": report,
                "database_writes": False, "write_approved": False}, []
    linked = {row["source_hash"] for row in links}
    counts = Counter(h for h in hashes if valid_hash(h))
    eligible = [r for r in candidates
                if valid_hash(r.get("google_source_id_hash"))
                and counts[r["google_source_id_hash"]] == 1
                and r["google_source_id_hash"] not in linked]
    # Check collisions across the ENTIRE observation, not just unlinked
    # candidates. A linked review can have a changed author or text that is
    # not yet reflected in its historical row. Invalid/duplicate source
    # observations must not conceal collisions either.
    author_counts = Counter(production.normalize_spaces(r["author"]).casefold()
                            for r in candidates)
    key_counts = Counter(production.canonical_review_hash(r) for r in candidates)
    mapping_held = Counter()
    safe = []
    source_by_key = {}
    for candidate in eligible:
        key = production.canonical_review_hash(candidate)
        author = production.normalize_spaces(candidate["author"]).casefold()
        if key_counts[key] != 1:
            mapping_held["canonical_key_collision"] += 1
            continue
        if author_counts[author] != 1:
            mapping_held["same_author_in_full_observation"] += 1
            continue
        if key in source_by_key:
            return held("SOURCE_APPEND_MAPPING_INVALID")
        source_by_key[key] = candidate["google_source_id_hash"]
        safe.append(candidate)
    # Existing rows and input candidates are not mutated.
    legacy, rows = build_append_preview(store, history, safe, production)
    hypothetical = []
    for row in rows:
        source = source_by_key.get(row["review_key"])
        if not valid_hash(source):
            return {"status": "SOURCE_APPEND_MAPPING_INVALID",
                    "database_writes": False, "write_approved": False}, []
        hypothetical.append((source, dict(row)))
    if (len({source for source, _ in hypothetical}) != len(hypothetical)
            or len({row["review_key"] for _, row in hypothetical}) != len(hypothetical)
            or len(safe) + sum(mapping_held.values()) != len(eligible)):
        return {"status": "SOURCE_APPEND_MAPPING_INVALID",
                "database_writes": False, "write_approved": False}, []
    return {"status": "SOURCE_APPEND_PREVIEW", "source_gate": report,
            "legacy_preview": legacy, "hypothetical_new_rows": len(hypothetical),
            "source_mapping_held": dict(mapping_held),
            "eligible_before_mapping": len(eligible),
            "eligible_after_mapping": len(safe),
            "database_writes": False, "write_approved": False}, hypothetical


def simulate_append_replay(store, history, candidates, production):
    """Simulate only hypothetical new rows and their links, then replay.

    A first pass with no verified registry does NOT assert a row is new.
    Do not create simulated links for existing or held reviews. No input
    records, source IDs, or temporary row payloads appear in the report.
    """
    before, rows = source_aware_preview(store, history, candidates, [], production)
    if before["status"] != "SOURCE_APPEND_PREVIEW":
        return {"status": "SOURCE_REPLAY_SIMULATION_BLOCKED", "database_writes": False, "write_approved": False}
    staged_history = [dict(row) for row in history]
    staged_links = []
    ids = {r["id"] for r in history}
    for source, row in rows:
        target = "fixture-preview:" + source
        if target in ids:
            return {"status": "SOURCE_REPLAY_SIMULATION_ID_CONFLICT", "database_writes": False, "write_approved": False}
        ids.add(target)
        staged_history.append(dict(row, id=target))
        staged_links.append({"store_id": store["id"], "source_hash": source, "review_id": target})
    after, replay_rows = source_aware_preview(store, staged_history, candidates, staged_links, production)
    # Change the mutable payload only for newly linked synthetic rows.
    linked = {r["source_hash"] for r in staged_links}
    changed = [dict(r, text="synthetic changed text", has_text=True, rating=1)
               if valid_hash(r.get("google_source_id_hash")) and r["google_source_id_hash"] in linked
               else dict(r) for r in candidates]
    changed_report, changed_rows = source_aware_preview(store, staged_history, changed, staged_links, production)
    passed = (bool(rows) and after["status"] == changed_report["status"] == "SOURCE_APPEND_PREVIEW"
              and not replay_rows and not changed_rows
              and after["source_gate"]["counts"].get("already_linked_no_insert", 0) == len(rows)
              and changed_report["source_gate"]["counts"].get("already_linked_no_insert", 0) == len(rows))
    return {"status": "SOURCE_REPLAY_SIMULATION_PASSED" if passed else
            ("SOURCE_REPLAY_NO_HYPOTHETICAL_ROWS" if not rows else "SOURCE_REPLAY_SIMULATION_GAPS"),
            "hypothetical_first_append": len(rows),
            "hypothetical_same_payload_replay": len(replay_rows),
            "hypothetical_changed_payload_replay": len(changed_rows),
            "simulated_links": len(staged_links),
            "real_links_persisted": 0, "actual_insert_count": 0,
            "database_writes": False, "write_approved": False}


def self_test():
    import scraper as production
    store = dict(id="S", store_name="Fixture", sv="SV", country="Country", is_active=True)
    a = dict(store_name="Fixture", author="A", rating=5, text="Exact fixture text", has_text=True,
             date="2 days ago", review_date="2026-11-22", collected_at="2026-11-24",
             review_date_source="estimated", google_source_id_hash="a"*64)
    b = dict(a, author="B", google_source_id_hash="b"*64)
    history = [dict(a, id="old", store_id="S", review_key=production.canonical_review_hash(a))]
    p = simulate_append_replay(store, history, [a,b], production)
    assert p["status"] == "SOURCE_REPLAY_SIMULATION_PASSED"
    assert p["hypothetical_first_append"] == 1 and p["simulated_links"] == 1
    assert p["hypothetical_same_payload_replay"] == p["hypothetical_changed_payload_replay"] == 0
    assert p["real_links_persisted"] == p["actual_insert_count"] == 0
    assert len(history) == 1 and history[0]["text"] == a["text"]
    assert p["write_approved"] is False
    link = {"store_id":"S","source_hash":"a"*64,"review_id":"old"}
    r, rows = source_aware_preview(store, history, [dict(a, text="changed", rating=1),b], [link], production)
    assert r["source_gate"]["counts"]["already_linked_no_insert"] == 1 and len(rows) == 1
    r, rows = source_aware_preview(store, history, [a,a,b], [link], production)
    assert r["source_gate"]["counts"]["duplicate_source_held"] == 2 and len(rows) == 1
    r, rows = source_aware_preview(store, history, [a,b], [dict(link,store_id="other")], production)
    assert r["status"] == "SOURCE_APPEND_BLOCKED" and not rows
    assert simulate_append_replay(store, history, [a], production)["status"] == "SOURCE_REPLAY_NO_HYPOTHETICAL_ROWS"
    assert simulate_append_replay(dict(store,is_active=False), history,[b],production)["status"] == "SOURCE_REPLAY_SIMULATION_BLOCKED"
    # A linked record with a changed author must still participate in
    # collision checks for unlinked reviews in the same observation.
    renamed = dict(a, author=b["author"], text="Changed linked payload")
    r, rows = source_aware_preview(store, history, [renamed,b], [link], production)
    assert not rows and r["source_mapping_held"] == {"same_author_in_full_observation":1}
    r, rows = source_aware_preview(store, history, [dict(b,google_source_id_hash="a"*64),b], [link], production)
    assert not rows and r["source_mapping_held"] == {"canonical_key_collision":1}
    r, rows = source_aware_preview(store, [], [a,dict(a,google_source_id_hash="c"*64)], [], production)
    assert not rows and r["source_mapping_held"] == {"canonical_key_collision":2}
    r, rows = source_aware_preview(store, [], [dict(a,google_source_id_hash=[]),b], [], production)
    assert len(rows)==1 and r["source_gate"]["counts"]["invalid_source_held"]==1
    r, rows = source_aware_preview(store, [], [dict(a,author=[])], [], production)
    assert r["status"]=="SOURCE_APPEND_INPUT_INVALID" and not rows
    r, rows = source_aware_preview(store, [], [None], [], production)
    assert r["status"]=="SOURCE_APPEND_INPUT_INVALID" and not rows
    r, rows = source_aware_preview(store, [None], [b], [], production)
    assert r["status"]=="SOURCE_APPEND_INPUT_INVALID" and not rows
    p = simulate_append_replay(store, [], [dict(a,google_source_id_hash=[]),b], production)
    assert p["status"]=="SOURCE_REPLAY_SIMULATION_PASSED"
    print("SOURCE_APPEND_REPLAY_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
