"""Local source append attempt journal prototype. No remote writes or credentials."""
import json
import re
import sqlite3
from pathlib import Path

from review_source_recovery import classify_recovery

HEX = re.compile(r"[0-9a-f]{64}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def valid(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


class AttemptJournal:
    """One unresolved attempt per store; never authorizes a write or retry.

    Caller must use a private local directory with appropriate OS permissions.
    No body, author, credential, or raw Google ID is accepted or stored.
    """
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
              attempt_id TEXT PRIMARY KEY, store_id TEXT NOT NULL,
              items TEXT NOT NULL, state TEXT NOT NULL
              CHECK(state IN ('PENDING','COMMITTED_CONFIRMED')) )""")
            self.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_pending_store
              ON attempts(store_id) WHERE state='PENDING'""")

    def close(self):
        self.db.close()

    def prepare(self, attempt_id, store_id, items):
        if not valid(attempt_id, UUID) or not valid(store_id, UUID) or not isinstance(items, list) or not 1 <= len(items) <= 500:
            raise ValueError("JOURNAL_INPUT_INVALID")
        seen = [set(), set(), set()]
        for item in items:
            if not isinstance(item, dict) or set(item) != {"store_id","source_hash","review_id","review_key"} or item["store_id"] != store_id:
                raise ValueError("JOURNAL_ITEM_INVALID")
            for i, (key, pattern) in enumerate((("source_hash",HEX),("review_id",UUID),("review_key",HEX))):
                value = item[key]
                if not valid(value,pattern) or value in seen[i]:
                    raise ValueError("JOURNAL_ITEM_INVALID")
                seen[i].add(value)
        with self.db:
            self.db.execute("INSERT INTO attempts VALUES (?,?,?,'PENDING')",
                            (attempt_id,store_id,json.dumps(items,sort_keys=True,separators=(',',':'))))
        return {"status":"JOURNAL_PENDING","write_approved":False}

    def pending_count(self):
        return self.db.execute("SELECT count(*) FROM attempts WHERE state='PENDING'").fetchone()[0]

    def recover(self, attempt_id, rows, links, *, snapshot_verified=False):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT store_id,items,state FROM attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if not row or row[2] != "PENDING":
                result = {"status":"JOURNAL_NO_PENDING_ATTEMPT","write_approved":False,"retry_authorized":False}
            else:
                result = classify_recovery(row[0],json.loads(row[1]),rows,links,snapshot_verified=snapshot_verified)
                # Only the complete exact-identity result can close an attempt.
                # Absent, mixed, or conflicting snapshots remain blocking.
                if result["status"] == "RECOVERY_COMMIT_CONFIRMED":
                    self.db.execute("UPDATE attempts SET state='COMMITTED_CONFIRMED' WHERE attempt_id=?",(attempt_id,))
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise


def self_test():
    from tempfile import TemporaryDirectory
    store = "10000000-0000-0000-0000-000000000001"
    aid = "20000000-0000-0000-0000-000000000001"
    other = "20000000-0000-0000-0000-000000000002"
    rid = "30000000-0000-0000-0000-000000000001"
    item = dict(store_id=store,source_hash="a"*64,review_id=rid,review_key="b"*64)
    row = dict(store_id=store,id=rid,review_key=item["review_key"])
    link = dict(store_id=store,source_hash=item["source_hash"],review_id=rid)
    with TemporaryDirectory() as tmp:
        path = Path(tmp)/"fixture.sqlite3"
        j = AttemptJournal(path)
        assert j.prepare(aid,store,[item])["write_approved"] is False
        assert j.pending_count() == 1
        j.close()
        j = AttemptJournal(path)
        assert j.pending_count() == 1
        try:
            j.prepare(other,store,[item])
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("second pending attempt accepted")
        assert j.recover(aid,[row],[link])["status"] == "RECOVERY_SNAPSHOT_UNVERIFIED"
        assert j.recover(aid,[],[],snapshot_verified=True)["status"] == "RECOVERY_FRESH_PLAN_REQUIRED"
        assert j.recover(aid,[row],[],snapshot_verified=True)["status"] == "RECOVERY_CONFLICT_HELD"
        assert j.pending_count() == 1
        assert j.recover(aid,[row],[link],snapshot_verified=True)["status"] == "RECOVERY_COMMIT_CONFIRMED"
        assert j.pending_count() == 0
        assert j.recover(aid,[row],[link],snapshot_verified=True)["status"] == "JOURNAL_NO_PENDING_ATTEMPT"
        try:
            j.prepare(other,store,[dict(item,body="must not store")])
        except ValueError:
            pass
        else:
            raise AssertionError("payload accepted")
        assert j.pending_count() == 0
        assert j.prepare(other,store,[item])["status"] == "JOURNAL_PENDING"
        j.close()
    print("SOURCE_ATTEMPT_JOURNAL_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
