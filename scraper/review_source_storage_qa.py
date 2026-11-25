"""SQLite transaction fixture only; no production or PostgreSQL connection."""
import sqlite3

DDL = """
CREATE TABLE reviews (
 id TEXT PRIMARY KEY, store_id TEXT NOT NULL, review_key TEXT NOT NULL UNIQUE,
 body TEXT NOT NULL, UNIQUE(store_id,id)
);
CREATE TABLE source_links (
 store_id TEXT NOT NULL, source_hash TEXT NOT NULL,
 review_id TEXT NOT NULL UNIQUE,
 CHECK(length(source_hash)=64 AND source_hash NOT GLOB '*[^0-9a-f]*'),
 PRIMARY KEY(store_id,source_hash),
 FOREIGN KEY(store_id,review_id) REFERENCES reviews(store_id,id) ON DELETE RESTRICT
);
"""


def append(db, store, row, key, body, source, *, fail_after_insert=False):
    """Fixture transaction, not a deployable writer or identity proof."""
    with db:
        found = db.execute('SELECT review_id FROM source_links WHERE store_id=? AND source_hash=?', (store,source)).fetchone()
        if found:
            return 'LINKED_NO_INSERT'
        db.execute('INSERT INTO reviews VALUES (?,?,?,?)', (row,store,key,body))
        if fail_after_insert:
            raise RuntimeError('SIMULATED_INTERRUPTION')
        db.execute('INSERT INTO source_links VALUES (?,?,?)', (store,source,row))
    return 'APPENDED'


def self_test():
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(DDL)
    db.execute('INSERT INTO reviews VALUES (?,?,?,?)', ('old','A','old-key','unchanged'))
    db.commit()
    snapshot = db.execute('SELECT * FROM reviews WHERE id=?', ('old',)).fetchone()
    a,b,c = 'a'*64,'b'*64,'c'*64
    assert append(db,'A','new','new-key','first',a) == 'APPENDED'
    assert append(db,'A','replay','changed-key','changed',a) == 'LINKED_NO_INSERT'
    assert db.execute('SELECT count(*) FROM reviews').fetchone()[0] == 2
    assert db.execute('SELECT body FROM reviews WHERE id=?', ('new',)).fetchone()[0] == 'first'
    def rejected(sql, args):
        try:
            with db:
                db.execute(sql,args)
        except sqlite3.IntegrityError:
            return
        raise AssertionError('constraint did not reject invalid row')
    rejected('INSERT INTO source_links VALUES (?,?,?)', ('B',b,'new'))
    rejected('INSERT INTO source_links VALUES (?,?,?)', ('A',b,'new'))
    rejected('INSERT INTO source_links VALUES (?,?,?)', ('A',a,'old'))
    rejected('INSERT INTO source_links VALUES (?,?,?)', ('A',c,'missing'))
    rejected('INSERT INTO source_links VALUES (?,?,?)', ('A','invalid','old'))
    try:
        append(db,'A','interrupted','interrupted-key','body',b,fail_after_insert=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError('expected interruption')
    assert db.execute('SELECT count(*) FROM reviews WHERE id=?', ('interrupted',)).fetchone()[0] == 0
    try:
        append(db,'A','collision','old-key','body',b)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('expected legacy collision')
    assert db.execute('SELECT count(*) FROM source_links').fetchone()[0] == 1
    assert append(db,'A','retry','retry-key','body',b) == 'APPENDED'
    assert db.execute('SELECT * FROM reviews WHERE id=?', ('old',)).fetchone() == snapshot
    assert db.execute('SELECT count(*) FROM reviews').fetchone()[0] == 3
    assert db.execute('SELECT count(*) FROM source_links').fetchone()[0] == 2
    db.close()
    print('SOURCE_STORAGE_SQLITE_FIXTURE_PASS')


if __name__ == '__main__':
    self_test()
