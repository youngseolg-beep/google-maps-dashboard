"""Read-only single-store Google Maps review coverage probe. No Supabase or Google login."""
import json
from playwright.sync_api import sync_playwright
from scraper import (
    build_url_candidates, click_cookie_buttons, get_review_cards,
    is_valid_google_maps_place_page, open_reviews_panel, scroll_reviews,
    wait_for_reviews,
)

STORE_URL = "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!16s%2Fg%2F11s674rmb9?entry=ttu"
MAX_ROUNDS = 30
STALL_LIMIT = 4


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="en-US", viewport={"width": 1365, "height": 900})
            opened = False
            for url in build_url_candidates(STORE_URL):
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(7000)
                click_cookie_buttons(page)
                if not is_valid_google_maps_place_page(page):
                    continue
                if not wait_for_reviews(page):
                    open_reviews_panel(page)
                page.wait_for_timeout(4000)
                if wait_for_reviews(page):
                    opened = True
                    break
            if not opened:
                print("COVERAGE_RESULT: " + json.dumps({"status": "REVIEW_PANEL_UNAVAILABLE", "observed": 0, "coverage": "unknown"}))
                raise SystemExit(2)

            max_seen = 0
            stalled = 0
            for round_no in range(1, MAX_ROUNDS + 1):
                cards, selector = get_review_cards(page)
                count = cards.count()
                max_seen = max(max_seen, count)
                print("COVERAGE_PROGRESS: " + json.dumps({"round": round_no, "visible_cards": count, "max_seen": max_seen}))
                if count > 0 and count > (max_seen if round_no == 1 else prior):
                    stalled = 0
                else:
                    stalled += 1
                if count > 0 and stalled >= STALL_LIMIT:
                    break
                prior = max_seen
                scroll_reviews(page)
                page.wait_for_timeout(1000)
            print("COVERAGE_RESULT: " + json.dumps({
                "status": "OBSERVED", "max_dom_cards": max_seen,
                "rounds": round_no, "full_coverage": "NOT_VERIFIED",
                "note": "DOM card count is not total unique reviews; compare with Maps displayed total separately"
            }))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
