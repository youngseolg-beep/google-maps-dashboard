"""Read-only audit of authenticated Google Maps candidates against existing Supabase reviews.

NO database writes. No review IDs, text, authors, session cookies or credentials
are persisted or printed. Results contain only aggregate counts per known store.
"""
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
import scraper as production
from review_multistore_probe import store_urls

REPORT = Path("review-auth-db-reconciliation-aggregate.json")
STORE_NAMES = {
    "Thailand": "Saemaeul Central Eastville",
    "Taiwan": "Bornga Dunnan Store",
    "Mongolia": "Saemaeul Seoul St.",
}
MAX_RECORDS_PER_STORE = 5000


def safe_maps_identity(value):
    """Compare the Maps place ID when present, otherwise a stable URL path."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if host == "maps.app.goo.gl":
        # Short links are case-sensitive. DB and repository must match exactly.
        return "short:" + parts.path.rstrip("/")
    if host not in {"google.com", "www.google.com", "maps.google.com"}:
        return None
    if not parts.path.startswith("/maps/"):
        return None
    cid = re.search(r"0x[0-9a-f]+:0x[0-9a-f]+", value, re.I)
    if cid:
        return "cid:" + cid.group(0).lower()
    return "path:" + parts.path.lower().rstrip("/")


def read_only_get(table, params, *, base, key):
    """Allowlisted GET only. Never support POST/PATCH/DELETE from audit code."""
    if table not in {"stores", "reviews"}:
        raise ValueError("TABLE_NOT_ALLOWED")
    url = base.rstrip("/") + "/rest/v1/" + table + "?" + urlencode(params, safe=",.*()")
    request = Request(url, headers={
        "apikey": key, "Authorization": "Bearer " + key,
        "Accept": "application/json",
    }, method="GET")
    with urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, list):
            raise ValueError("UNEXPECTED_DATABASE_RESULT")
        return result


def load_existing_store_reviews(store_id, *, base, key):
    rows = []
    offset = 0
    while True:
        batch = read_only_get("reviews", {
            "select": "id,store_id,store_name,author,rating,text,review_text,date,review_date,review_key,has_text",
            "store_id": "eq." + store_id,
            "order": "id.asc",
            "limit": "500",
            "offset": str(offset),
        }, base=base, key=key)
        rows.extend(batch)
        if len(rows) > MAX_RECORDS_PER_STORE:
            raise RuntimeError("REVIEW_READ_LIMIT_EXCEEDED")
        if len(batch) < 500:
            break
        offset += 500
    return rows


def compare_candidates(candidates, saved, store_name):
    """Compare only memory-local review data. No raw values in result."""
    saved_hashes = {x.get("review_key") for x in saved if x.get("review_key")}
    normalized_saved = [{
        "store_name": store_name,
        "author": x.get("author") or "Anonymous",
        "rating": x.get("rating"),
        "date": x.get("date") or "Unknown",
        "review_date": x.get("review_date") or "",
        "text": x.get("text") or x.get("review_text") or "",
    } for x in saved]
    saved_keys = {production.make_review_key(x) for x in normalized_saved}
    counts = {
        "live_candidates": len(candidates),
        "existing_db_rows": len(saved),
        "exact_stored_hash_matches": 0,
        "normalized_existing_matches_only": 0,
        "expanded_text_variant_matches_only": 0,
        "potential_new_candidates": 0,
        "empty_text_candidates": 0,
        "candidate_key_duplicates": 0,
        "saved_noncanonical_review_keys": 0,
    }
    counts["saved_noncanonical_review_keys"] = sum(
        bool(row.get("review_key")) and
        row["review_key"] != production.canonical_review_hash({
            "store_name": store_name,
            "author": row.get("author") or "Anonymous",
            "text": row.get("text") or row.get("review_text") or "",
        }) for row in saved
    )
    processed = set()
    for item in candidates:
        key = production.make_review_key(item)
        if key in processed:
            counts["candidate_key_duplicates"] += 1
            continue
        processed.add(key)
        if not (item.get("text") or "").strip():
            counts["empty_text_candidates"] += 1
        digest = production.canonical_review_hash(item)
        if digest in saved_hashes:
            counts["exact_stored_hash_matches"] += 1
        elif key in saved_keys:
            counts["normalized_existing_matches_only"] += 1
        elif production.find_existing_review_match(item, normalized_saved, saved_keys):
            counts["expanded_text_variant_matches_only"] += 1
        else:
            counts["potential_new_candidates"] += 1
    counts["matching_or_potential_total"] = (
        counts["exact_stored_hash_matches"]
        + counts["normalized_existing_matches_only"]
        + counts["expanded_text_variant_matches_only"]
        + counts["potential_new_candidates"]
        + counts["candidate_key_duplicates"]
    )
    return counts


def main():
    base = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    outcome = {
        "status": "NOT_STARTED", "database_writes": False,
        "review_contents_persisted": False, "complete_coverage_verified": False,
        "stores": [],
    }
    if not base.startswith("https://") or not key:
        outcome["status"] = "DATABASE_CREDENTIALS_MISSING"
        finish(outcome, fail=True)
        return
    try:
        target_urls = {
            country: url for _, country, url in store_urls()
            if country in STORE_NAMES
        }
        all_db_stores = read_only_get("stores", {
            "select": "id,store_name,country,google_maps_url,is_active",
            "limit": "1000",
        }, base=base, key=key)
        selected = {}
        for country, name in STORE_NAMES.items():
            rows = [
                row for row in all_db_stores
                if row.get("store_name") == name
                and row.get("country") == country
                and row.get("is_active") is True
            ]
            if len(rows) != 1 or not target_urls.get(country):
                raise ValueError("MISSING_OR_AMBIGUOUS_STORE_MAPPING")
            db_identity = safe_maps_identity(rows[0].get("google_maps_url"))
            live_identity = safe_maps_identity(target_urls[country])
            if not db_identity or db_identity != live_identity:
                raise ValueError("STORE_GOOGLE_MAPS_IDENTITY_MISMATCH")
            selected[country] = rows[0]
        # Restrict to one known Google account, with in-memory authentication.
        auth = production.load_dedicated_google_auth_state()
        if auth is None:
            raise RuntimeError("AUTH_SECRET_MISSING")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage", "--no-sandbox",
                "--disable-setuid-sandbox", "--lang=en-US,en",
            ])
            try:
                context = production.new_crawler_context(browser, auth_state=auth)
                try:
                    context.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    )
                    page = context.new_page()
                    page.set_default_timeout(45000)
                    page.goto("https://www.google.com/maps",
                              wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                    if not production.verify_dedicated_google_login(page):
                        raise RuntimeError("GOOGLE_AUTH_SESSION_NOT_VISIBLE")
                    for country, db_name in STORE_NAMES.items():
                        store = selected[country]
                        existing = load_existing_store_reviews(
                            store["id"], base=base, key=key
                        )
                        target = {
                            "store_name": db_name, "sv": "READ_ONLY_AUDIT",
                            "country": country, "city": "",
                            "url": target_urls[country],
                        }
                        try:
                            evidence = {}
                            with contextlib.redirect_stdout(io.StringIO()), \
                                 contextlib.redirect_stderr(io.StringIO()):
                                result = production.scrape_store(
                                    page, target, existing_reviews=[],
                                    collection_evidence=evidence,
                                    force_english_ui=True,
                                )
                            candidates = result.get("reviews", [])
                            row = {
                                "store": db_name, "country": country,
                                "extraction_status": (
                                    "SCANNED" if result.get("ok") else "PARTIAL_OR_FAILED"
                                ),
                                "observed_review_count": evidence.get("observed_review_count", 0),
                                "collection_issue": result.get("collection_issue"),
                                "completeness_verified": False,
                                **compare_candidates(candidates, existing, db_name),
                            }
                        except Exception as exc:
                            row = {
                                "store": db_name, "country": country,
                                "extraction_status": "ERROR",
                                "exception_type": type(exc).__name__,
                                "existing_db_rows": len(existing),
                                "completeness_verified": False,
                            }
                        outcome["stores"].append(row)
                        print("READ_ONLY_STORE_RECONCILIATION: " + json.dumps(row, ensure_ascii=False))
                    outcome["status"] = (
                        "PASS" if all(x.get("extraction_status") == "SCANNED"
                            and x.get("matching_or_potential_total") == x.get("live_candidates")
                            for x in outcome["stores"]) else "PARTIAL"
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        # Never log detailed third-party errors, as these may include sensitive URLs.
        outcome["status"] = "ERROR"
        outcome["error_type"] = type(exc).__name__
    finish(outcome, fail=outcome["status"] != "PASS")


def finish(outcome, fail=False):
    REPORT.write_text(json.dumps(outcome, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print("READ_ONLY_DB_RECONCILIATION_VERDICT: " + json.dumps(outcome, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Authenticated Maps vs existing Supabase reviews (GET-only)\n\n")
            f.write("Result: **" + outcome["status"] + "**. No database changes.\n\n")
            f.write("| Store | Existing DB | Observed | Exact hash | Normalized | Text variants | Potential new | Coverage |\n")
            f.write("|---|---:|---:|---:|---:|---:|---:|---|\n")
            for x in outcome["stores"]:
                f.write("| " + x["store"] + " | " + str(x.get("existing_db_rows", 0))
                        + " | " + str(x.get("live_candidates", 0))
                        + " | " + str(x.get("exact_stored_hash_matches", 0))
                        + " | " + str(x.get("normalized_existing_matches_only", 0))
                        + " | " + str(x.get("expanded_text_variant_matches_only", 0))
                        + " | " + str(x.get("potential_new_candidates", 0))
                        + " | NOT VERIFIED |\n")
            f.write("\nPotential new is a candidate count only, not approved for insertion.\n")
    if fail:
        sys.exit(2)


if __name__ == "__main__":
    main()
