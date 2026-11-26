"""End-to-end synthetic interruption QA. Never connects to a remote database."""
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from review_source_storage_qa import DDL
from review_source_attempt_journal import AttemptJournal
from review_incremental_baseline import BaselineFixture
from review_incremental_boundary import preview_boundary
from review_incremental_capture import _capture_plan

STORE = "10000000-0000-0000-0000-000000000001"


def item(i):
    return dict(store_id=STORE, source_hash=f"{i:064x}",
                review_id=f"20000000-0000-0000-0000-{i:012x}",
                review_key=f"{i+1000:064x}")


def fixture_db(path):
    db = sqlite3.connect(str(path))
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db


def append_fixture_batch(db, items, *, interrupt_after=None, body_by_key=None):
    """Atomic synthetic review/link transaction, not a production writer."""
    db.execute("BEGIN IMMEDIATE")
    try:
        for index, entry in enumerate(items, 1):
            db.execute("INSERT INTO reviews VALUES (?,?,?,?)",
                       (entry["review_id"], entry["store_id"], entry["review_key"],
                        body_by_key[entry["review_key"]] if body_by_key is not None else "fixture body"))
            db.execute("INSERT INTO source_links VALUES (?,?,?)",
                       (entry["store_id"], entry["source_hash"], entry["review_id"]))
            if index == interrupt_after:
                raise RuntimeError("FIXTURE_BEFORE_COMMIT")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def snapshot(db):
    """Read both fixture tables in the same SQLite transaction."""
    db.execute("BEGIN")
    try:
        rows = [dict(id=r[0], store_id=r[1], review_key=r[2], body=r[3])
                for r in db.execute("SELECT id,store_id,review_key,body FROM reviews WHERE store_id=? ORDER BY id", (STORE,))]
        links = [dict(store_id=r[0], source_hash=r[1], review_id=r[2])
                 for r in db.execute("SELECT store_id,source_hash,review_id FROM source_links WHERE store_id=? ORDER BY source_hash", (STORE,))]
        db.commit()
        return rows, links
    except BaseException:
        db.rollback()
        raise


def self_test():
    from datetime import date
    import scraper as production
    from local_review_profile_probe import adapt_local_records
    store=dict(id=STORE,store_name="Fixture",sv="SV",country="Country",is_active=True)
    base=date(2026,11,26)
    def record(i):
        return dict(source_id=f"fixture-{i}",author=f"Fixture Author {i}",rating=5,
                    body=f"Fixture review {i}",body_scope="PRIMARY",
                    date_label="2 days ago",body_complete_verified=True)
    raw_old=[record(i) for i in range(1,31)]
    raw_new=[record(101),record(102)]
    adapted,gaps=adapt_local_records(raw_old,store["store_name"],base,production,store_id=STORE)
    assert len(adapted)==30 and not any(gaps.values())
    old=[dict(item(i),source_hash=r["google_source_id_hash"],
              review_key=production.canonical_review_hash(r)) for i,r in enumerate(adapted,1)]
    history=[dict(r,id=x["review_id"],store_id=STORE,review_key=x["review_key"])
             for r,x in zip(adapted,old)]
    old_bodies={x["review_key"]:r["text"] for x,r in zip(old,adapted)}
    head=[r["source_hash"] for r in old]
    observed=[production.hash_google_source_review_id(STORE,r["source_id"]) for r in raw_new]+head
    aid = "30000000-0000-0000-0000-000000000001"
    aid2 = "30000000-0000-0000-0000-000000000002"
    flags = dict(newest_verified=True, snapshot_verified=True, capture_verified=True)
    # Independent fixture stores model local journal/checkpoint and a remote
    # append transaction. No concurrency or real remote authority is proven.
    for interrupted_before_commit in (True, False):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = fixture_db(root/"storage.sqlite3")
            db.executescript(DDL)
            append_fixture_batch(db, old, body_by_key=old_bodies)
            before_rows, before_links = snapshot(db)
            journal = AttemptJournal(root/"journal.sqlite3")
            baseline = BaselineFixture(root/"baseline.sqlite3")
            try:
                def advance(generation, hashes, *, initial=False):
                    rows, links = snapshot(db)
                    return baseline.advance(STORE,generation,hashes,rows,links,
                                            pending_attempts=journal.pending_count(),
                                            initial_coverage_verified=initial,**flags)["status"]
                assert advance(0,head,initial=True)=="BASELINE_FIXTURE_ADVANCED"
                before = baseline.read(STORE)
                boundary = preview_boundary(STORE,dict(before,committed=True,newest_verified=True),
                                            observed,set(head),newest_verified=True,
                                            registry_verified=True,context_verified=True)
                assert boundary["status"]=="INCREMENTAL_BOUNDARY_CANDIDATE"
                assert boundary["unlinked_prefix"]==2 and not boundary["write_approved"]
                def plan(records,**overrides):
                    return _capture_plan(store,dict(before,committed=True,newest_verified=True),
                                         records,history,before_links,production,adapt_local_records,base,
                                         **dict(dict(flags,context_verified=True,pending_attempts=journal.pending_count()),**overrides))
                report,pairs=plan(raw_new+raw_old)
                assert report["status"]=="CAPTURE_APPEND_PREVIEW" and not report["write_approved"]
                assert len(pairs)==2 and [h for h,_ in pairs]==observed[:2]
                assert [r["text"] for _,r in pairs]==[r["body"] for r in raw_new]
                for bad in ([dict(raw_new[0],body_complete_verified=False),raw_new[1]]+raw_old,
                            [dict(raw_new[0],author=raw_old[0]["author"]),raw_new[1]]+raw_old,
                            raw_new+raw_old[:-1]):
                    rejected,empty=plan(bad)
                    assert rejected["status"]!="CAPTURE_APPEND_PREVIEW" and not empty
                fresh=[dict(item(i),source_hash=h,review_key=r["review_key"])
                       for i,(h,r) in enumerate(pairs,101)]
                fresh_bodies={r["review_key"]:r["text"] for _,r in pairs}
                journal.prepare(aid,STORE,fresh)
                rejected,empty=plan(raw_new+raw_old)
                assert rejected["status"]=="CAPTURE_EVIDENCE_HELD" and not empty
                assert advance(1,observed)=="BASELINE_EVIDENCE_HELD"
                try:
                    append_fixture_batch(db,fresh,interrupt_after=1 if interrupted_before_commit else None,
                                         body_by_key=fresh_bodies)
                except RuntimeError as exc:
                    assert interrupted_before_commit and str(exc)=="FIXTURE_BEFORE_COMMIT"
                else:
                    assert not interrupted_before_commit
                # Simulate restart after the write response was lost.
                db.close()
                journal.close()
                baseline.close()
                db=fixture_db(root/"storage.sqlite3")
                journal=AttemptJournal(root/"journal.sqlite3")
                baseline=BaselineFixture(root/"baseline.sqlite3")
                assert journal.pending_count()==1
                assert baseline.read(STORE)==before
                assert advance(1,observed)=="BASELINE_EVIDENCE_HELD"
                try:
                    journal.prepare(aid2,STORE,fresh)
                except sqlite3.IntegrityError:
                    pass
                else:
                    raise AssertionError("SECOND_PENDING_ATTEMPT_ACCEPTED")
                rows,links=snapshot(db)
                assert journal.recover(aid,rows,links)["status"]=="RECOVERY_SNAPSHOT_UNVERIFIED"
                recovered=journal.recover(aid,rows,links,snapshot_verified=True)
                assert not recovered["write_approved"] and not recovered["retry_authorized"]
                if interrupted_before_commit:
                    assert recovered["status"]=="RECOVERY_FRESH_PLAN_REQUIRED"
                    assert rows==before_rows and links==before_links
                    assert journal.pending_count()==1
                    assert advance(1,observed)=="BASELINE_EVIDENCE_HELD"
                    assert baseline.read(STORE)==before
                else:
                    assert recovered["status"]=="RECOVERY_COMMIT_CONFIRMED"
                    assert journal.pending_count()==0
                    assert len(rows)==len(links)==32
                    assert {r["review_key"]:r["body"] for r in rows if r["review_key"] in fresh_bodies}==fresh_bodies
                    assert [r for r in rows if r["id"] in {x["id"] for x in before_rows}]==before_rows
                    assert advance(1,observed)=="BASELINE_FIXTURE_ADVANCED"
                    assert baseline.read(STORE)["head"]==observed[:30]
                    assert baseline.read(STORE)["generation"]==2
                    assert advance(1,observed)=="BASELINE_GENERATION_CONFLICT"
                    assert journal.recover(aid,rows,links,snapshot_verified=True)["status"]=="JOURNAL_NO_PENDING_ATTEMPT"
                    assert snapshot(db)==(rows,links)
            finally:
                baseline.close()
                journal.close()
                db.close()
    print("INCREMENTAL_TRANSACTION_FIXTURE_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
