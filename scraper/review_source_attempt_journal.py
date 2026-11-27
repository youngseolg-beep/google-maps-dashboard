"""Local source append attempt journal prototype. No remote writes or credentials."""
import json
import os
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
    The legacy attempts table stores hashes only. Live source_requests also
    stores original review payloads for recovery; credentials and raw IDs
    are never part of those requests.
    """
    def __init__(self, path):
        self.path = Path(path).resolve()
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
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

    def bind_backend(self, identity):
        """A staging journal must never replay requests into another project."""
        if not isinstance(identity,str) or not identity:
            raise ValueError('JOURNAL_BACKEND_INVALID')
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS source_backend (singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL)')
            self.db.execute('INSERT INTO source_backend VALUES (1,?) ON CONFLICT DO NOTHING',(identity,))
            if self.db.execute('SELECT identity FROM source_backend WHERE singleton=1').fetchone()[0] != identity:
                raise ValueError('JOURNAL_BACKEND_MISMATCH')

    def prepare_request(self, request):
        """Durable live-writer envelope. Contains review bodies; keep outside Git."""
        if self.path.is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError('LIVE_JOURNAL_MUST_BE_OUTSIDE_REPOSITORY')
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS source_requests (
                operation_id TEXT PRIMARY KEY, store_id TEXT NOT NULL,
                payload TEXT NOT NULL, result TEXT)""")
            operation = request['p_operation_id']
            payload = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False)
            self.db.execute('INSERT INTO source_requests VALUES (?,?,?,NULL) ON CONFLICT DO NOTHING',
                            (operation, request['p_store_id'], payload))
            if self.db.execute('SELECT payload FROM source_requests WHERE operation_id=?', (operation,)).fetchone()[0] != payload:
                raise ValueError('JOURNAL_REQUEST_CONFLICT')
        return operation

    def pending_requests(self, store_id):
        # Initialize the table even on a fresh process with no prepared request.
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS source_requests (operation_id TEXT PRIMARY KEY, store_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT)')
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT payload FROM source_requests WHERE store_id=? AND result IS NULL ORDER BY rowid', (store_id,))]

    def confirm_request(self, request, result):
        if (not isinstance(result, dict) or result.get('operation_id') != request['p_operation_id']
                or not isinstance(result.get('outcomes'), list)
                or type(result.get('boundary_advanced')) is not bool):
            raise ValueError('SOURCE_RECEIPT_INVALID')
        expected = [item['source_hash'] for item in request['p_items']]
        outcomes = result['outcomes']
        if ([item.get('source_hash') for item in outcomes] != expected or any(
                item.get('status') not in {'inserted','existing_source','linked_legacy','unresolved'} for item in outcomes)):
            raise ValueError('SOURCE_RECEIPT_INCOMPLETE')
        if any(item['status'] != 'unresolved' and not valid(item.get('review_id'), UUID) for item in outcomes):
            raise ValueError('SOURCE_RECEIPT_IDENTITY_INVALID')
        with self.db:
            self.db.execute('UPDATE source_requests SET result=? WHERE operation_id=? AND result IS NULL',
                            (json.dumps(result, sort_keys=True), request['p_operation_id']))

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
