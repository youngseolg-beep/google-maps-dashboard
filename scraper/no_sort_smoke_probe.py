"""Read-only one-store smoke test of the production scraper's no-sort fallback."""
import json
from playwright.sync_api import sync_playwright
from scraper import scrape_store

STORE = {
    "store_name": "Saemaeul Central Eastville",
    "sv": "TEST",
    "country": "Thailand",
    "city": "Bangkok",
    "url": "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!16s%2Fg%2F11s674rmb9?entry=ttu",
}
# A synthetic existing row activates the existing-review path without DB access.
EXISTING = [{
    "store_name": STORE["store_name"],
    "author": "__coverage_probe_nonexistent_author__",
    "text": "__coverage_probe_nonexistent_text__",
    "rating": 1,
    "date": "100 years ago",
}]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--lang=en-US,en",
            ],
        )
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="Asia/Seoul",
                viewport={"width": 1440, "height": 1000},
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = context.new_page()
            page.set_default_timeout(45000)
            result = scrape_store(page, STORE, existing_reviews=EXISTING)
            # Read-only DOM geometry: identify whether the five review cards live
            # inside a nested scrollable container rather than the selected feed.
            scroll_candidates = page.evaluate("""() => {
                const card = document.querySelector('.jftiEf');
                if (!card) return [];
                const nodes = [];
                for (let el = card.parentElement; el && nodes.length < 12; el = el.parentElement) {
                    const style = getComputedStyle(el);
                    const height = el.scrollHeight - el.clientHeight;
                    if (height > 30 || el.getAttribute('role') === 'feed') {
                        nodes.push({
                            tag: el.tagName.toLowerCase(),
                            role: el.getAttribute('role') || '',
                            overflowY: style.overflowY,
                            scrollable_px: Math.round(height),
                            scroll_top: Math.round(el.scrollTop),
                            cards: el.querySelectorAll('.jftiEf').length
                        });
                    }
                }
                return nodes;
            }""")
            print("REVIEW_SCROLL_ANCESTORS: " + json.dumps(scroll_candidates, separators=(',', ':')))
            # Never log review text, author, account data, or URLs from extracted reviews.
            print("NO_SORT_SMOKE_RESULT: " + json.dumps({
                "ok": result["ok"],
                "extracted_review_candidates": len(result["reviews"]),
                "error_type": result.get("collection_issue") or ("none" if result["ok"] else "other"),
                "database_writes": False,
                "full_coverage_verified": False,
            }, sort_keys=True))
            if not result["ok"]:
                raise SystemExit(2)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
