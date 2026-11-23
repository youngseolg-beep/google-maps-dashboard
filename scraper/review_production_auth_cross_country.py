"""Read-only authenticated production scraper validation for Taiwan and Mongolia.

Uses URLs already mapped in index.html and actual production scrape_store.
No Supabase credentials, database operations, screenshots or review text
are permitted in logs or artifacts; values exist only transiently in memory.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
import scraper as production
from review_multistore_probe import store_urls

REPORT = Path("review-production-auth-cross-country-result.json")
TARGET_COUNTRIES = ("Taiwan", "Mongolia")


def summarize_result(store, scanned, evidence):
    reviews = scanned.get("reviews", [])
    keys = {production.make_review_key(item) for item in reviews}
    return {
        "store": store["store_name"],
        "country": store["country"],
        "status": "SCANNED" if scanned.get("ok") else "CRAWLER_REPORTED_FAILURE",
        "review_count": len(reviews),
        "review_keys_unique": len(keys),
        "key_collisions": len(reviews) - len(keys),
        "authors_parsed": sum(
            x.get("author") not in ("Anonymous", "", None) for x in reviews
        ),
        "ratings_valid": sum(
            type(x.get("rating")) is int and 1 <= x["rating"] <= 5
            for x in reviews
        ),
        "dates_parsed": sum(
            x.get("date") not in ("Unknown", "", None) for x in reviews
        ),
        "text_present": sum(bool(x.get("text")) for x in reviews),
        "text_empty": sum(not bool(x.get("text")) for x in reviews),
        "observed_review_count": evidence.get("observed_review_count", 0),
        "collection_issue": scanned.get("collection_issue"),
        "completeness_verified": False,
    }


def run():
    if os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("READ_ONLY_REFUSES_DB_SECRETS")
    output = {
        "database_writes": False,
        "review_content_persisted": False,
        "target_countries": list(TARGET_COUNTRIES),
        "account_ui": False,
        "stores": [],
        "all_stores_six_plus": False,
        "all_stores_parsed": False,
        "status": "NOT_STARTED",
    }
    try:
        targets = [
            {"store_name": name, "country": country,
             "sv": "READ_ONLY_DIAGNOSTIC", "city": "", "url": url}
            for name, country, url in store_urls()
            if country in TARGET_COUNTRIES
        ]
        if len(targets) != len(TARGET_COUNTRIES):
            raise ValueError("Missing known store in repository mapping")
        auth = production.load_dedicated_google_auth_state()
        if auth is None:
            output["status"] = "AUTH_STATE_MISSING"
        else:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage", "--no-sandbox",
                        "--disable-setuid-sandbox", "--lang=en-US,en",
                    ],
                )
                try:
                    context = production.new_crawler_context(
                        browser, auth_state=auth
                    )
                    try:
                        context.add_init_script(
                            "Object.defineProperty(navigator,'webdriver',"
                            "{get:()=>undefined});"
                        )
                        page = context.new_page()
                        page.set_default_timeout(45000)
                        page.goto(
                            "https://www.google.com/maps",
                            wait_until="domcontentloaded", timeout=45000
                        )
                        page.wait_for_timeout(3000)
                        output["account_ui"] = (
                            production.verify_dedicated_google_login(page)
                        )
                        if not output["account_ui"]:
                            output["status"] = "AUTH_UI_NOT_ACCEPTED"
                        else:
                            output["status"] = "TEST_RUNNING"
                            for store in targets:
                                # The production crawler may print review IDs
                                # and errors; discard stdout and stderr instead
                                # of exposing them in public Actions logs.
                                evidence = {}
                                try:
                                    with contextlib.redirect_stdout(io.StringIO()), \
                                         contextlib.redirect_stderr(io.StringIO()):
                                        scanned = production.scrape_store(
                                            page, store, existing_reviews=[],
                                            collection_evidence=evidence,
                                        )
                                    row = summarize_result(store, scanned, evidence)
                                except Exception as exc:
                                    row = {
                                        "store": store["store_name"],
                                        "country": store["country"],
                                        "status": "EXTRACTION_ERROR",
                                        "exception_type": type(exc).__name__,
                                        "review_count": 0,
                                        "completeness_verified": False,
                                    }
                                output["stores"].append(row)
                                # Never log individual review content, IDs or
                                # author names, even after store completion.
                                print("CROSS_COUNTRY_STORE_AGGREGATE: " + json.dumps(row))
                                page.wait_for_timeout(1500)
                            output["all_stores_six_plus"] = all(
                                x.get("review_count", 0) >= 6 and
                                x.get("status") == "SCANNED" for x in output["stores"]
                            )
                            output["all_stores_parsed"] = all(
                                x.get("review_count", 0) == x.get("review_keys_unique")
                                == x.get("ratings_valid") == x.get("dates_parsed")
                                and x.get("key_collisions") == 0
                                for x in output["stores"]
                            )
                            output["status"] = (
                                "PASS" if output["all_stores_six_plus"]
                                and output["all_stores_parsed"] else "PARTIAL"
                            )
                    finally:
                        context.close()
                finally:
                    browser.close()
    except Exception as exc:
        output["status"] = "EXCEPTION"
        output["exception_type"] = type(exc).__name__
    REPORT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("CROSS_COUNTRY_PRODUCTION_VERDICT: " + json.dumps({
        "status": output["status"],
        "account_ui": output["account_ui"],
        "all_stores_six_plus": output["all_stores_six_plus"],
        "all_stores_parsed": output["all_stores_parsed"],
        "stores": output["stores"],
        "database_writes": False,
    }, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Cross-country authenticated production crawler test\n\n")
            f.write("**" + output["status"] + "** — no DB access or review content persisted.\n\n")
            f.write("| Country | Store | Parsed reviews | Key collisions | Coverage |\n")
            f.write("|---|---|---:|---:|---|\n")
            for row in output["stores"]:
                f.write("| " + row["country"] + " | " + row["store"] +
                        " | " + str(row.get("review_count", 0)) +
                        " | " + str(row.get("key_collisions", "?")) +
                        " | unverified |\n")
    if output["status"] != "PASS":
        sys.exit(2)


if __name__ == "__main__":
    run()
