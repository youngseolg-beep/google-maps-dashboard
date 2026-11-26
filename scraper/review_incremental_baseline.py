"""Isolated SQLite checkpoint fixture; not a production baseline authority."""
import json
import re
import sqlite3

HEX = re.compile(r"[0-9a-f]{64}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def valid(v, pattern):
    return isinstance(v, str) and pattern.fullmatch(v) is not None


class BaselineFixture:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                store_id TEXT PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>0),
                head TEXT NOT NULL)""")

    def close(self):
        self.db.close()

    def read(self, store_id):
        row = self.db.execute("SELECT generation,head FROM checkpoints WHERE store_id=?", (store_id,)).fetchone()
        if not row:
            return None
        head = json.loads(row[1])
        if not valid(store_id, UUID) or not isinstance(head,list) or len(head)!=30 or any(not valid(h,HEX) for h in head) or len(set(head))!=30:
            raise ValueError("CHECKPOINT_INVALID")
        return dict(store_id=store_id, generation=row[0], head=head, fixture_only=True)

    def advance(self, store_id, generation, observed, rows, links, *,
                newest_verified=False, snapshot_verified=False, capture_verified=False,
                pending_attempts=None, initial_coverage_verified=False):
        """Fixture-only CAS. Flags model evidence, not actual browser/DB proof."""
        def result(status):
            return dict(status=status, fixture_only=True, write_approved=False,
                        stop_authorized=False, database_writes=False)
        if not valid(store_id,UUID) or type(generation) is not int or generation<0:
            return result("BASELINE_INPUT_INVALID")
        if not all(v is True for v in (newest_verified,snapshot_verified,capture_verified)) or type(pending_attempts) is not int or pending_attempts!=0:
            return result("BASELINE_EVIDENCE_HELD")
        if generation==0 and initial_coverage_verified is not True:
            return result("BASELINE_INITIAL_COVERAGE_HELD")
        if not isinstance(observed,list) or not 30<=len(observed)<=1000 or any(not valid(h,HEX) for h in observed) or len(set(observed))!=len(observed):
            return result("BASELINE_OBSERVATION_INVALID")
        if not isinstance(rows,list) or not isinstance(links,list):
            return result("BASELINE_SNAPSHOT_INVALID")
        targets, keys, sources, used = {}, set(), {}, set()
        for row in rows:
            if not isinstance(row,dict) or row.get("store_id")!=store_id:
                return result("BASELINE_SNAPSHOT_INVALID")
            rid,key = row.get("id"),row.get("review_key")
            if not valid(rid,UUID) or not valid(key,HEX) or rid in targets or key in keys:
                return result("BASELINE_SNAPSHOT_INVALID")
            targets[rid]=key
            keys.add(key)
        for link in links:
            if not isinstance(link,dict) or link.get("store_id")!=store_id:
                return result("BASELINE_SNAPSHOT_INVALID")
            source,rid = link.get("source_hash"),link.get("review_id")
            if not valid(source,HEX) or not valid(rid,UUID) or rid not in targets or source in sources or rid in used:
                return result("BASELINE_SNAPSHOT_INVALID")
            sources[source]=rid
            used.add(rid)
        if not set(observed).issubset(sources):
            return result("BASELINE_UNCOMMITTED_IDS_HELD")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old=self.read(store_id)
            if (old["generation"] if old else 0)!=generation:
                report=result("BASELINE_GENERATION_CONFLICT")
            elif old and (not set(old["head"]).issubset(sources) or old["head"][0] not in observed or observed[observed.index(old["head"][0]):][:30]!=old["head"]):
                report=result("BASELINE_OVERLAP_HELD")
            else:
                head=json.dumps(observed[:30],separators=(",",":"))
                self.db.execute("INSERT INTO checkpoints VALUES (?,?,?) ON CONFLICT(store_id) DO UPDATE SET generation=excluded.generation,head=excluded.head",(store_id,generation+1,head))
                report=result("BASELINE_FIXTURE_ADVANCED")
            self.db.commit()
            return report
        except BaseException:
            self.db.rollback()
            raise


def self_test():
    from tempfile import TemporaryDirectory
    from pathlib import Path
    store="10000000-0000-0000-0000-000000000001"
    observed=[f"{i:064x}" for i in range(1,32)]
    rows=[dict(store_id=store,id=f"20000000-0000-0000-0000-{i:012x}",review_key=f"{i+100:064x}") for i in range(1,32)]
    links=[dict(store_id=store,source_hash=h,review_id=r["id"]) for h,r in zip(observed,rows)]
    flags=dict(newest_verified=True,snapshot_verified=True,capture_verified=True,pending_attempts=0,initial_coverage_verified=True)
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"fixture.sqlite3"
        a=BaselineFixture(path)
        def run(g,obs=observed,rr=rows,ll=links,**changes):
            p=a.advance(store,g,obs,rr,ll,**dict(flags,**changes))
            assert not p["write_approved"] and not p["database_writes"] and not p["stop_authorized"]
            return p["status"]
        assert run(0,initial_coverage_verified=False)=="BASELINE_INITIAL_COVERAGE_HELD"
        assert run(0,pending_attempts=1)=="BASELINE_EVIDENCE_HELD"
        assert run(0,snapshot_verified=False)=="BASELINE_EVIDENCE_HELD"
        assert run(0,ll=links[:-1])=="BASELINE_UNCOMMITTED_IDS_HELD"
        assert run(0,ll=links+[links[0]])=="BASELINE_SNAPSHOT_INVALID"
        assert a.read(store) is None
        assert run(0)=="BASELINE_FIXTURE_ADVANCED"
        a.close()
        a=BaselineFixture(path)
        before=a.read(store)
        assert before["generation"]==1 and before["head"]==observed[:30]
        assert run(0)=="BASELINE_GENERATION_CONFLICT"
        assert run(1,obs=list(reversed(observed)))=="BASELINE_OVERLAP_HELD"
        assert run(1,capture_verified=False)=="BASELINE_EVIDENCE_HELD"
        assert a.read(store)==before
        fresh=observed[-1:]+observed[:30]
        assert run(1,obs=fresh)=="BASELINE_FIXTURE_ADVANCED"
        assert a.read(store)["generation"]==2 and a.read(store)["head"]==fresh[:30]
        a.close()
    print("INCREMENTAL_BASELINE_FIXTURE_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
