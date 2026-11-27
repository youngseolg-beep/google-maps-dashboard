-- REVIEW REQUIRED. Apply separately after isolated rehearsal and approval.
-- Existing review rows and review_key values are never rewritten.
BEGIN;
CREATE UNIQUE INDEX reviews_store_identity_idx ON public.reviews(store_id,id);
CREATE TABLE public.review_source_links (
 store_id uuid NOT NULL REFERENCES public.stores(id) ON DELETE RESTRICT,
 source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
 review_id uuid NOT NULL UNIQUE,
 FOREIGN KEY(store_id,review_id) REFERENCES public.reviews(store_id,id) ON DELETE RESTRICT,
 PRIMARY KEY(store_id,source_hash)
);
CREATE TABLE public.review_source_receipts (
 operation_id uuid PRIMARY KEY, store_id uuid NOT NULL REFERENCES public.stores(id),
 request jsonb NOT NULL, result jsonb NOT NULL
);
CREATE TABLE public.review_source_baselines (
 store_id uuid PRIMARY KEY REFERENCES public.stores(id),
 generation bigint NOT NULL CHECK(generation > 0), head jsonb NOT NULL
);
ALTER TABLE public.review_source_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_source_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_source_baselines ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.review_source_links, public.review_source_receipts, public.review_source_baselines FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.review_source_links, public.review_source_receipts TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.review_source_baselines TO service_role;

CREATE FUNCTION public.append_review_sources(p_operation_id uuid, p_store_id uuid,
 p_items jsonb, p_finalize jsonb DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
DECLARE
 request_value jsonb := jsonb_build_object('items',p_items,'finalize',p_finalize);
 saved public.review_source_receipts%ROWTYPE;
 baseline public.review_source_baselines%ROWTYPE;
 item jsonb; body jsonb; target uuid; source text; outcome text;
 outcomes jsonb := '[]'; result_value jsonb; proposed jsonb; observed jsonb;
 expected bigint; anchor integer; advanced boolean := false;
BEGIN
 IF p_operation_id IS NULL OR p_store_id IS NULL OR jsonb_typeof(p_items) IS DISTINCT FROM 'array'
    OR jsonb_array_length(p_items) > 250 THEN RAISE EXCEPTION 'invalid append scope'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('review-source:' || p_store_id::text,0));
 SELECT * INTO saved FROM public.review_source_receipts WHERE operation_id=p_operation_id;
 IF FOUND THEN
   IF saved.store_id <> p_store_id OR saved.request <> request_value THEN
     RAISE EXCEPTION 'operation identity conflict';
   END IF;
   RETURN saved.result;
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_items) x GROUP BY x->>'source_hash' HAVING count(*)>1) THEN
   RAISE EXCEPTION 'duplicate source in request';
 END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
   source := item->>'source_hash'; target := NULL;
   IF source IS NULL OR source !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid source'; END IF;
   SELECT review_id INTO target FROM public.review_source_links WHERE store_id=p_store_id AND source_hash=source;
   IF target IS NOT NULL THEN outcome := 'existing_source';
   ELSE
     body := item->'row';
     IF item->>'legacy_id' IS NOT NULL THEN
       -- A legacy link never edits its target. Revalidate the proposed match.
       SELECT id INTO target FROM public.reviews r WHERE r.id=(item->>'legacy_id')::uuid
         AND r.store_id=p_store_id AND r.author=body->>'author'
         AND coalesce(nullif(r.text,''),r.review_text,'')=body->>'text'
         AND r.rating=(body->>'rating')::numeric
         AND coalesce(r.date,r.relative_date,'')=coalesce(body->>'date','')
         AND NOT EXISTS(SELECT 1 FROM public.review_source_links l WHERE l.review_id=r.id);
       outcome := 'linked_legacy';
     ELSE
       IF jsonb_typeof(body) IS DISTINCT FROM 'object' OR body->>'store_id' IS DISTINCT FROM p_store_id::text
          OR body->>'review_key' IS NULL OR body->>'author' IS NULL
          OR jsonb_typeof(body->'rating') IS DISTINCT FROM 'number' OR (body->>'rating')::numeric NOT BETWEEN 1 AND 5
          OR jsonb_typeof(body->'text') IS DISTINCT FROM 'string'
          OR (body->>'has_text')::boolean IS DISTINCT FROM (length(btrim(body->>'text'))>0)
          OR NOT EXISTS(SELECT 1 FROM public.stores s WHERE s.id=p_store_id AND s.is_active
                        AND s.store_name=body->>'store_name') THEN
         RAISE EXCEPTION 'invalid review row';
       END IF;
       INSERT INTO public.reviews(review_key,store_id,store_name,sv,country,city,author,rating,
         text,has_text,date,review_date,review_date_source,collected_at,scraped_at,source,first_seen_run_id)
       VALUES(body->>'review_key',p_store_id,body->>'store_name',body->>'sv',body->>'country',body->>'city',
         body->>'author',(body->>'rating')::numeric,body->>'text',(body->>'has_text')::boolean,
         body->>'date',body->>'review_date',body->>'review_date_source',
         (body->>'collected_at')::timestamptz,(body->>'scraped_at')::timestamptz,'google_maps',
         (body->>'first_seen_run_id')::bigint)
       ON CONFLICT DO NOTHING RETURNING id INTO target;
       outcome := 'inserted';
     END IF;
     IF target IS NULL THEN outcome := 'unresolved';
     ELSE
       INSERT INTO public.review_source_links VALUES(p_store_id,source,target);
     END IF;
   END IF;
   outcomes := outcomes || jsonb_build_array(jsonb_build_object('source_hash',source,'status',outcome,'review_id',target));
 END LOOP;
 IF p_finalize IS NOT NULL THEN
   SELECT * INTO baseline FROM public.review_source_baselines WHERE store_id=p_store_id;
   expected := (p_finalize->>'generation')::bigint;
   observed := p_finalize->'observed'; proposed := observed->0;
   IF p_finalize->>'newest_verified'='true' AND p_finalize->>'resolved'='true'
      AND jsonb_typeof(observed)='array' AND jsonb_array_length(observed) BETWEEN 30 AND 10000
      AND expected=coalesce(baseline.generation,0)
      AND (SELECT count(DISTINCT value) FROM jsonb_array_elements(observed))=jsonb_array_length(observed)
      AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(observed) h WHERE NOT EXISTS(
          SELECT 1 FROM public.review_source_links l WHERE l.store_id=p_store_id AND l.source_hash=h)) THEN
     IF expected=0 THEN
       advanced := p_finalize->>'initial_complete'='true';
     ELSE
       SELECT ordinality::integer INTO anchor FROM jsonb_array_elements(observed) WITH ORDINALITY
         WHERE value=baseline.head->0;
       advanced := anchor IS NOT NULL AND jsonb_array_length(observed)>=anchor+29 AND
         NOT EXISTS(SELECT 1 FROM generate_series(0,29) i WHERE observed->(anchor-1+i) <> baseline.head->i);
     END IF;
     IF advanced THEN
       SELECT jsonb_agg(value ORDER BY ordinality) INTO proposed FROM jsonb_array_elements(observed)
         WITH ORDINALITY WHERE ordinality<=30;
       INSERT INTO public.review_source_baselines VALUES(p_store_id,expected+1,proposed)
       ON CONFLICT(store_id) DO UPDATE SET generation=excluded.generation,head=excluded.head;
     END IF;
   END IF;
 END IF;
 result_value := jsonb_build_object('operation_id',p_operation_id,'outcomes',outcomes,'boundary_advanced',coalesce(advanced,false));
 INSERT INTO public.review_source_receipts VALUES(p_operation_id,p_store_id,request_value,result_value);
 RETURN result_value;
END $$;
REVOKE ALL ON FUNCTION public.append_review_sources(uuid,uuid,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.append_review_sources(uuid,uuid,jsonb,jsonb) TO service_role;
COMMIT;
