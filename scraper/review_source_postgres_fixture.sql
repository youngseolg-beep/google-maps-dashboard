-- Synthetic PostgreSQL fixture ONLY. Not a migration.
BEGIN;
CREATE ROLE fixture_anon NOLOGIN;
CREATE ROLE fixture_authenticated NOLOGIN;
CREATE ROLE fixture_writer NOLOGIN;
CREATE SCHEMA fixture_private;
REVOKE ALL ON SCHEMA fixture_private FROM PUBLIC, fixture_anon, fixture_authenticated;
CREATE TABLE fixture_private.reviews (
 id uuid PRIMARY KEY, store_id uuid NOT NULL, review_key text NOT NULL UNIQUE,
 body text NOT NULL, UNIQUE(store_id,id)
);
CREATE TABLE fixture_private.source_links (
 store_id uuid NOT NULL, source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
 review_id uuid NOT NULL UNIQUE,
 PRIMARY KEY(store_id,source_hash),
 FOREIGN KEY(store_id,review_id) REFERENCES fixture_private.reviews(store_id,id) ON DELETE RESTRICT
);
ALTER TABLE fixture_private.reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE fixture_private.source_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA fixture_private FROM PUBLIC,fixture_anon,fixture_authenticated;
GRANT USAGE ON SCHEMA fixture_private TO fixture_writer;
GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA fixture_private TO fixture_writer;
CREATE POLICY writer_read_reviews ON fixture_private.reviews FOR SELECT TO fixture_writer USING (true);
CREATE POLICY writer_insert_reviews ON fixture_private.reviews FOR INSERT TO fixture_writer WITH CHECK (true);
CREATE POLICY writer_read_links ON fixture_private.source_links FOR SELECT TO fixture_writer USING (true);
CREATE POLICY writer_insert_links ON fixture_private.source_links FOR INSERT TO fixture_writer WITH CHECK (true);
CREATE FUNCTION fixture_private.append_fixture(s uuid, h text, r uuid, k text, b text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
BEGIN
 IF s IS NULL OR h IS NULL OR h !~ '^[0-9a-f]{64}$' THEN
   RAISE EXCEPTION 'invalid fixture source';
 END IF;
 -- Serialize fixture operations on a store. Legacy writers not using this
 -- lock are not covered; database constraints remain mandatory.
 PERFORM pg_advisory_xact_lock(hashtextextended('fixture-source:' || s::text, 0));
 IF EXISTS(SELECT 1 FROM fixture_private.source_links WHERE store_id=s AND source_hash=h) THEN
   RETURN 'LINKED_NO_INSERT';
 END IF;
 INSERT INTO fixture_private.reviews VALUES(r,s,k,b);
 INSERT INTO fixture_private.source_links VALUES(s,h,r);
 RETURN 'APPENDED';
END $$;
REVOKE ALL ON FUNCTION fixture_private.append_fixture(uuid,text,uuid,text,text) FROM PUBLIC,fixture_anon,fixture_authenticated;
GRANT EXECUTE ON FUNCTION fixture_private.append_fixture(uuid,text,uuid,text,text) TO fixture_writer;
INSERT INTO fixture_private.reviews VALUES('00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','old-key','unchanged');
COMMIT;
DO $$
BEGIN
 IF has_schema_privilege('fixture_anon','fixture_private','USAGE')
 OR has_schema_privilege('fixture_authenticated','fixture_private','USAGE')
 OR has_table_privilege('fixture_anon','fixture_private.source_links','SELECT')
 OR has_table_privilege('fixture_authenticated','fixture_private.source_links','INSERT')
 OR has_function_privilege('fixture_anon','fixture_private.append_fixture(uuid,text,uuid,text,text)','EXECUTE')
 OR has_function_privilege('fixture_authenticated','fixture_private.append_fixture(uuid,text,uuid,text,text)','EXECUTE')
 OR has_table_privilege('fixture_writer','fixture_private.reviews','UPDATE')
 OR has_table_privilege('fixture_writer','fixture_private.source_links','DELETE') THEN
   RAISE EXCEPTION 'fixture grant violation';
 END IF;
END $$;
SET ROLE fixture_writer;
DO $$
DECLARE s uuid := '10000000-0000-0000-0000-000000000001';
        r uuid := '00000000-0000-0000-0000-000000000002';
BEGIN
 IF fixture_private.append_fixture(s,repeat('a',64),r,'new-key','original') <> 'APPENDED' THEN RAISE EXCEPTION 'append failed'; END IF;
 IF fixture_private.append_fixture(s,repeat('a',64),'00000000-0000-0000-0000-000000000003','different-key','translated') <> 'LINKED_NO_INSERT' THEN RAISE EXCEPTION 'replay failed'; END IF;
 BEGIN
   PERFORM fixture_private.append_fixture(s,repeat('b',64),'00000000-0000-0000-0000-000000000003','old-key','collision');
   RAISE EXCEPTION 'legacy constraint missing';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
 BEGIN
   INSERT INTO fixture_private.source_links VALUES('10000000-0000-0000-0000-000000000002',repeat('c',64),'00000000-0000-0000-0000-000000000001');
   RAISE EXCEPTION 'cross-store constraint missing';
 EXCEPTION WHEN foreign_key_violation THEN NULL;
 END;
 BEGIN
   INSERT INTO fixture_private.source_links VALUES(s,repeat('d',64),r);
   RAISE EXCEPTION 'target constraint missing';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
 BEGIN
   PERFORM fixture_private.append_fixture(s,repeat('b',64),'00000000-0000-0000-0000-000000000004','rollback-key','rollback');
   RAISE EXCEPTION 'fixture forced interruption' USING ERRCODE='P0002';
 EXCEPTION WHEN no_data_found THEN NULL;
 END;
 IF (SELECT count(*) FROM fixture_private.reviews) <> 2
 OR (SELECT count(*) FROM fixture_private.source_links) <> 1
 OR NOT EXISTS (SELECT 1 FROM fixture_private.reviews WHERE review_key='old-key' AND body='unchanged')
 OR NOT EXISTS (SELECT 1 FROM fixture_private.reviews WHERE review_key='new-key' AND body='original') THEN
   RAISE EXCEPTION 'fixture data mismatch';
 END IF;
END $$;
RESET ROLE;
SET ROLE fixture_anon;
DO $$ BEGIN
 BEGIN
   PERFORM count(*) FROM fixture_private.source_links;
   RAISE EXCEPTION 'anon access unexpectedly granted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SET ROLE fixture_authenticated;
DO $$ BEGIN
 BEGIN
   PERFORM fixture_private.append_fixture('10000000-0000-0000-0000-000000000001',repeat('e',64),'00000000-0000-0000-0000-000000000005','forbidden','forbidden');
   RAISE EXCEPTION 'authenticated execution unexpectedly granted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
SELECT 'POSTGRES_FIXTURE_SERIAL_PASS';
