"""Read-only Google Maps auth/newest proof for ephemeral GitHub Actions runners."""
import base64
import json
import os
from playwright.sync_api import sync_playwright
from scraper import open_reviews_panel, has_review_dom, is_valid_google_maps_place_page

URL = "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!16s%2Fg%2F11s674rmb9?entry=ttu"

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
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            if page.get_by_role("button", name="Accept all").count():
                page.get_by_role("button", name="Accept all").first.click(timeout=3000)
            print("PAGE_DIAG: url_is_maps_place=" + str("/maps/place/" in page.url))
            print("PAGE_DIAG: place_detail_detected=" + str(is_valid_google_maps_place_page(page)))
            print("PAGE_DIAG: review_dom_initial=" + str(has_review_dom(page)))
            if not open_reviews_panel(page):
                raise RuntimeError("REVIEWS_PANEL_NOT_OPENED: check page-detail or consent/interstitial; auth remains unverified")
            page.wait_for_timeout(3000)
            import re
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
