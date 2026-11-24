"""Isolated review-language and author-overlap diagnosis across three stores.

Read-only: GET-only Supabase queries, no writes or persisted review text,
author information, review identifiers, cookies, keys or screenshots.
Only aggregate counts and language-script distributions leave memory.
"""
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright
import scraper as production
from review_multistore_probe import store_urls
from review_auth_db_reconciliation import (
    STORE_NAMES, read_only_get, load_existing_store_reviews,
    safe_maps_identity,
)

REPORT = Path("review-auth-text-language-audit-aggregate.json")


def language_flags(value):
    value = value or ""
    return {
        "latin": bool(re.search(r"[A-Za-z]", value)),
        "han": bool(re.search(r"[\u4e00-\u9fff]", value)),
        "thai": bool(re.search(r"[\u0E00-\u0E7F]", value)),
        "cyrillic": bool(re.search(r"[\u0400-\u04FF]", value)),
        "hangul": bool(re.search(r"[\uAC00-\uD7AF]", value)),
    }


def normalize_author(value):
    return production.normalize_spaces(value).casefold()


def sample_reviews(page):
    # Stable IDs, author names, bodies are read only in memory.
    result = {}
    cards = page.locator(".jftiEf")
    for i in range(min(cards.count(), 40)):
        try:
            card = cards.nth(i)
            rid = card.get_attribute("data-review-id")
            if not rid:
                continue
            result[rid] = {
                "author": production.get_review_author(card),
                "rating": production.get_review_rating(card),
                "text": production.get_review_text(card),
            }
        except Exception:
            continue
    return result


def summarize(sample, saved, store_name):
    db_authors = {normalize_author(r.get("author")) for r in saved}
    db_author_rating = {
        (normalize_author(r.get("author")), str(r.get("rating") or "").strip())
        for r in saved
    }
    db_keys = {r.get("review_key") for r in saved}
    counts = {
        "cards": len(sample), "author_seen_in_db": 0,
        "author_rating_seen_in_db": 0, "exact_key_seen_in_db": 0,
        "has_text": 0,
        "latin_text": 0, "han_text": 0, "thai_text": 0,
        "cyrillic_text": 0, "hangul_text": 0,
    }
    for item in sample.values():
        author = normalize_author(item["author"])
        if author in db_authors:
            counts["author_seen_in_db"] += 1
        rating_str = str(item["rating"])
        # Numeric rating from DB may serialize as 5 or 5.0.
        if (author, rating_str) in db_author_rating or (
            author, rating_str + ".0"
        ) in db_author_rating:
            counts["author_rating_seen_in_db"] += 1
        if production.canonical_review_hash({
            "store_name": store_name,
            "author": item["author"], "text": item["text"],
        }) in db_keys:
            counts["exact_key_seen_in_db"] += 1
        if item["text"]:
            counts["has_text"] += 1
        for label, yes in language_flags(item["text"]).items():
            if yes:
                counts[label + "_text"] += 1
    return counts



def append_english_language_to_maps_url(value):
    """Only Google Maps place destinations; never account/security URLs."""
    u = urlsplit(value)
    if u.scheme != "https" or (u.hostname or "").lower() not in {
        "google.com", "www.google.com", "maps.google.com"
    } or not u.path.startswith("/maps/"):
        raise ValueError("NOT_A_GOOGLE_MAPS_URL")
    query = "&".join(
        part for part in u.query.split("&")
        if part and not part.lower().startswith(("hl=", "gl="))
    )
    query += ("&" if query else "") + "hl=en&gl=us"
    return urlunsplit((u.scheme,u.netloc,u.path,query,u.fragment))

def run():
    base = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    output = {"status": "NOT_STARTED", "database_writes": False,
              "review_contents_persisted": False, "stores": []}
    if not base.startswith("https://") or not key:
        output["status"] = "DATABASE_CREDENTIALS_MISSING"
        finish(output, fail=True)
        return
    try:
        urls = {
            country: url for _, country, url in store_urls()
            if country in STORE_NAMES
        }
        stores = read_only_get("stores", {
            "select": "id,store_name,country,google_maps_url,is_active",
            "limit": "1000",
        }, base=base, key=key)
        selected = {}
        for country, name in STORE_NAMES.items():
            candidates = [s for s in stores
                          if s.get("store_name") == name
                          and s.get("country") == country
                          and s.get("is_active") is True]
            if len(candidates) != 1 or safe_maps_identity(
                candidates[0]["google_maps_url"]
            ) != safe_maps_identity(urls[country]):
                raise RuntimeError("STORE_URL_MISMATCH")
            selected[country] = candidates[0]

        auth = production.load_dedicated_google_auth_state()
        if auth is None:
            raise RuntimeError("AUTH_MISSING")
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
                    page.set_default_timeout(15000)
                    page.goto("https://www.google.com/maps",
                              wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2000)
                    if not production.verify_dedicated_google_login(page):
                        raise RuntimeError("AUTH_UI_NOT_CONFIRMED")

                    for country, name in STORE_NAMES.items():
                        rows = load_existing_store_reviews(
                            selected[country]["id"], base=base, key=key
                        )
                        row = {"country": country, "store": name,
                               "db_rows": len(rows), "status": "STARTED"}
                        try:
                            page.goto(urls[country], wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(5500)
                            with contextlib.redirect_stdout(io.StringIO()), \
                                 contextlib.redirect_stderr(io.StringIO()):
                                opened = production.open_all_reviews_control(page)
                                if not opened:
                                    opened = production.open_reviews_panel(page)
                            page.wait_for_timeout(1800)
                            before = sample_reviews(page)
                            controls = page.get_by_role("button", name=re.compile(
                                r"See original|Show original|Original|원문 보기|원본 보기|"
                                r"Bekijk origineel|Origineel bekijken|Lihat asli|Tampilkan asli", re.I
                            )).count()
                            with contextlib.redirect_stdout(io.StringIO()), \
                                 contextlib.redirect_stderr(io.StringIO()):
                                production.click_original_review_buttons(page)
                            page.wait_for_timeout(700)
                            after = sample_reviews(page)
                            common_ids = set(before) & set(after)
                            changed = sum(
                                before[rid]["text"] != after[rid]["text"]
                                for rid in common_ids
                            )
                            db_lang = {name: sum(language_flags(
                                r.get("text") or r.get("review_text") or ""
                            )[name] for r in rows)
                                       for name in ("latin","han","thai","cyrillic","hangul")}
                            # A signed-in Google account can override
                            # Playwright locale and present Korean-translated
                            # text. Request an English Maps UI without changing
                            # Google account settings.
                            en_url = append_english_language_to_maps_url(page.url)
                            page.goto(en_url, wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(5200)
                            with contextlib.redirect_stdout(io.StringIO()), \
                                 contextlib.redirect_stderr(io.StringIO()):
                                en_opened = production.open_all_reviews_control(page)
                                if not en_opened:
                                    en_opened = production.open_reviews_panel(page)
                            page.wait_for_timeout(1500)
                            english = sample_reviews(page)
                            overlap_en = set(before) & set(english)
                            row.update({
                                "status": "SAMPLED",
                                "full_review_action_confirmed": bool(opened),
                                "original_buttons_before": controls,
                                "same_ids_before_after": len(common_ids),
                                "text_changed_after_original": changed,
                                "before": summarize(before, rows, name),
                                "after": summarize(after, rows, name),
                                "forced_english": summarize(english, rows, name),
                                "forced_english_reviews_opened": bool(en_opened),
                                "same_ids_before_and_forced_en": len(overlap_en),
                                "text_changed_after_forced_en": sum(
                                    before[rid]["text"] != english[rid]["text"]
                                    for rid in overlap_en
                                ),
                                "account_ui_after_en": production.verify_dedicated_google_login(page),
                                "db_language_counts": db_lang,
                            })
                        except Exception as exc:
                            row.update({"status":"ERROR",
                                        "exception_type":type(exc).__name__})
                        output["stores"].append(row)
                        print("REVIEW_TEXT_VARIANT_STORE: " + json.dumps(row,ensure_ascii=False))
                    output["status"] = ("PASS" if all(
                        r.get("status")=="SAMPLED" and
                        r.get("before", {}).get("cards", 0)>=6
                        for r in output["stores"]) else "PARTIAL")
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        output["status"] = "ERROR"
        output["exception_type"] = type(exc).__name__
    finish(output, fail=output["status"] != "PASS")


def finish(output, fail):
    REPORT.write_text(json.dumps(output, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print("REVIEW_TEXT_VARIANT_VERDICT: "+json.dumps(output,ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Review text language/identity diagnosis\n\n")
            f.write("Status: **" + output["status"] + "**. GET-only DB access; no review data persisted.\n")
    if fail:
        sys.exit(2)


if __name__ == "__main__":
    run()
