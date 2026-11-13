"""Read-only Google Maps auth/newest proof for ephemeral GitHub Actions runners."""
import base64
import json
import os
from playwright.sync_api import sync_playwright
import re
from scraper import open_reviews_panel, has_review_dom, is_valid_google_maps_place_page

URL = "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!16s%2Fg%2F11s674rmb9?entry=ttu"

def safe_panel_diagnostics(page):
    """Only booleans/counts: no cookies, page text, URLs or screenshots."""
    selectors = {
        "review_feed": "div[role=feed]",
        "review_cards": ".jftiEf",
        "review_articles": "div[role=article]",
        "review_text": ".wiI7pd",
        "review_sort_buttons": "button[aria-label*=Sort], button[aria-label*=sort], button[aria-label*=정렬]",
        "review_tab": "[role=tab][aria-selected=true]",
    }
    for label, selector in selectors.items():
        try:
            print(f"PANEL_DIAG: {label}={min(page.locator(selector).count(), 100)}")
        except Exception:
            print(f"PANEL_DIAG: {label}=ERROR")
    print("PANEL_DIAG: place_detail=" + str(is_valid_google_maps_place_page(page)))
    print("PANEL_DIAG: google_consent=" + str("consent.google" in page.url))
    print("PANEL_DIAG: account_signin=" + str("accounts.google" in page.url))

def main():
    encoded = os.environ.get("GOOGLE_MAPS_STORAGE_STATE_B64", "")
    if not encoded:
        raise RuntimeError("AUTH_NOT_CONFIGURED: GOOGLE_MAPS_STORAGE_STATE_B64 secret is missing")
    try:
        state = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            raise ValueError("invalid storage state")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AUTH_STATE_INVALID: secret must be base64 JSON Playwright storage_state") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=state, locale="en-US", viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            response_counts = {"maps_2xx": 0, "maps_3xx": 0, "maps_4xx": 0, "maps_5xx": 0, "maps_other": 0}
            request_failures = {"maps_failed": 0}
            failure_types = {}
            def record_response(response):
                if "google.com/maps" not in response.url and "google.com/$rpc" not in response.url:
                    return
                status = response.status
                key = "maps_2xx" if 200 <= status < 300 else "maps_3xx" if 300 <= status < 400 else "maps_4xx" if 400 <= status < 500 else "maps_5xx" if 500 <= status < 600 else "maps_other"
                response_counts[key] += 1
            def record_failed(request):
                if "google.com/maps" in request.url or "google.com/$rpc" in request.url:
                    request_failures["maps_failed"] += 1
                    failure = request.failure or "UNKNOWN"
                    if "ERR_ABORTED" in failure:
                        kind = "ERR_ABORTED"
                    elif "ERR_TIMED_OUT" in failure:
                        kind = "ERR_TIMED_OUT"
                    elif "ERR_CONNECTION" in failure:
                        kind = "ERR_CONNECTION"
                    elif "ERR_FAILED" in failure:
                        kind = "ERR_FAILED"
                    elif "ERR_NAME_NOT_RESOLVED" in failure:
                        kind = "ERR_NAME_NOT_RESOLVED"
                    else:
                        kind = "OTHER"
                    failure_types[kind] = failure_types.get(kind, 0) + 1
            page.on("response", record_response)
            page.on("requestfailed", record_failed)
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            if page.get_by_role("button", name="Accept all").count():
                page.get_by_role("button", name="Accept all").first.click(timeout=3000)
            print("PAGE_DIAG: url_is_maps_place=" + str("/maps/place/" in page.url))
            print("PAGE_DIAG: place_detail_detected=" + str(is_valid_google_maps_place_page(page)))
            print("PAGE_DIAG: review_dom_initial=" + str(has_review_dom(page)))
            panel_opened = open_reviews_panel(page)
            if not panel_opened:
                page.wait_for_timeout(8000)
                safe_panel_diagnostics(page)
                print("NETWORK_DIAG: " + json.dumps({**response_counts, **request_failures}, sort_keys=True))
                print("NETWORK_FAILURE_TYPES: " + json.dumps(failure_types, sort_keys=True))
                print("PAGE_DIAG: maps_page_title_present=" + str(bool(page.title().strip())))
                if not has_review_dom(page):
                    raise RuntimeError("REVIEWS_PANEL_NOT_OPENED: review DOM absent after extra wait; auth remains unverified")
            page.wait_for_timeout(3000)
            sort = page.get_by_role("button", name=re.compile(r"Sort|정렬|Sorteer|Sorteren|Urutkan", re.I))
            if not sort.count():
                raise RuntimeError("SORT_BUTTON_NOT_FOUND")
            sort.first.click(timeout=10000)
            newest = page.get_by_role("menuitemradio", name="Newest")
            if not newest.count():
                newest = page.get_by_role("menuitem", name="Newest")
            if not newest.count():
                newest = page.get_by_text("Newest", exact=True)
            if not newest.count() or not newest.first.is_visible():
                raise RuntimeError("NEWEST_OPTION_NOT_AVAILABLE: session may not be authenticated")
            newest.first.click(timeout=10000)
            page.wait_for_timeout(3000)
            print("NEWEST_CLICKED: newest option selected; login identity still not independently verified")
            print("NOTE: actual chronological ordering and session persistence across runs remain unverified")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
