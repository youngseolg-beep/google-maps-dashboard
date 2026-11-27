-- Synthetic fixture for test_live_source_writer.py. Fresh isolated cluster only.
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE ROLE fixture_login LOGIN NOINHERIT;
GRANT service_role TO fixture_login;
CREATE TABLE public.sv_writer_fixture(marker text NOT NULL);
CREATE TABLE public.stores (
 id uuid PRIMARY KEY, store_name text NOT NULL, sv text, country text,
 city text, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE public.reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), store_id uuid NOT NULL REFERENCES public.stores(id),
 review_key text NOT NULL UNIQUE, store_name text, sv text, country text,city text,author text,
 rating numeric(2,1), text text,review_text text,date text,relative_date text,
 has_text boolean,review_date text,review_date_source text,collected_at timestamptz,
 scraped_at timestamptz,source text,first_seen_run_id bigint
);
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;
GRANT USAGE ON SCHEMA public TO service_role;
GRANT SELECT,INSERT ON public.stores,public.reviews TO service_role;
GRANT SELECT ON public.sv_writer_fixture TO service_role;

-- Existing crawl_runs shape, synthetic integration fixture only.
CREATE TABLE public.crawl_runs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 last_crawled_at text,total_stores integer,success_count integer,failed_count integer,
 failed_stores jsonb,stores jsonb
);
GRANT SELECT,INSERT,UPDATE ON public.crawl_runs TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.crawl_runs_id_seq TO service_role;
