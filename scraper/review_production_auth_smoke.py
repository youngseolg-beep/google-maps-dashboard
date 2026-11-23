"""Run actual production scrape_store against one authenticated Maps store.

Read-only: never connect to Supabase, write reviews, log account fields,
persist original review data/IDs/text or capture screenshots.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
import scraper as production
from review_entry_matrix_probe import ORIGINAL

REPORT = Path("review-production-auth-smoke-report.json")
STORE = {
    "store_name": "Saemaeul Central Eastville",
    "sv": "READ_ONLY_DIAGNOSTIC",
    "country": "Thailand",
    "city": "",
    "url": ORIGINAL,
}


def main():
    if os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("READ_ONLY_TEST_REFUSES_DB_CREDENTIALS")
    outcome = {
        "target": STORE["store_name"],
        "database_writes": False,
        "review_data_persisted": False,
        "status": "NOT_STARTED",
        "review_count": 0,
        "review_keys_unique": 0,
        "key_collisions": 0,
        "text_present": 0,
        "missing_date": 0,
        "ratings_valid": 0,
        "collection_issue": None,
        "account_ui": False,
    }
    try:
        auth = production.load_dedicated_google_auth_state()
        if auth is None:
            outcome["status"] = "AUTH_SECRET_MISSING"
        else:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--lang=en-US,en",
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
                        page.wait_for_timeout(3000)
                        outcome["account_ui"] = production.verify_dedicated_google_login(page)
                        if not outcome["account_ui"]:
                            outcome["status"] = "ACCOUNT_UI_NOT_ACCEPTED"
                        else:
                            evidence = {}
                            # Production may log card fingerprints or exceptions.
                            # Keep all raw logger output strictly in ephemeral memory.
                            with contextlib.redirect_stdout(io.StringIO()):
                                scanned = production.scrape_store(
                                    page, STORE, existing_reviews=[],
                                    collection_evidence=evidence
                                )
                            rows = scanned.get("reviews", [])
                            keys = {production.make_review_key(x) for x in rows}
                            outcome.update({
                                "status": ("SCANNED" if scanned.get("ok")
                                           else "CRAWLER_REPORTED_FAILURE"),
                                "review_count": len(rows),
                                "review_keys_unique": len(keys),
                                "key_collisions": len(rows) - len(keys),
                                "text_present": sum(bool(x.get("text")) for x in rows),
                                "missing_date": sum(x.get("date") in ("", "Unknown", None)
                                                    for x in rows),
                                "ratings_valid": sum(type(x.get("rating")) is int
                                                     and 1 <= x["rating"] <= 5 for x in rows),
                                "collection_issue": scanned.get("collection_issue"),
                                "observed_review_count": evidence.get("observed_review_count", 0),
                                "read_only_completeness_verified": False,
                            })
                    finally:
                        context.close()
                finally:
                    browser.close()
    except Exception as exc:
        # Do not emit third-party exception messages; may include page/URLs.
        outcome["status"] = "EXCEPTION"
        outcome["exception_type"] = type(exc).__name__

    REPORT.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PRODUCTION_AUTH_INTEGRATION_VERDICT: " + json.dumps(outcome, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Read-only production scraper authentication integration\n\n")
            f.write("| Field | Value |\n|---|---|\n")
            for name, value in outcome.items():
                f.write("| " + str(name) + " | " + str(value) + " |\n")
            f.write("\nNo review text, author, IDs or auth data persisted or printed. No Supabase access.\n")
    if outcome["status"] != "SCANNED" or outcome["review_count"] < 100 or outcome["key_collisions"] > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
