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
            # Capture the initial panel state without exposing page content.
            page.goto(STORE["url"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            initial_panel = page.evaluate("""() => ({
                cards: document.querySelectorAll('.jftiEf').length,
                review_feeds: [...document.querySelectorAll('[role="feed"]')]
                    .filter(el => el.querySelector('.jftiEf')).length,
                review_buttons: [...document.querySelectorAll('button')]
                    .filter(el => /reviews|리뷰/i.test(el.getAttribute('aria-label') || '')).length
            })""")
            print("REVIEW_ENTRY_DIAGNOSTIC: " + json.dumps(initial_panel, sort_keys=True))
            # Distinguish an unopened review feed from cards rendered in place details.
            # Only element counts, roles and scroll geometry are recorded.
            initial_card_layout = page.evaluate("""() => {
                const cards = [...document.querySelectorAll('.jftiEf')];
                return {
                    cards: cards.length,
                    in_dialog: cards.filter(c => c.closest('[role="dialog"]')).length,
                    in_feed: cards.filter(c => c.closest('[role="feed"]')).length,
                    in_scrollable_ancestor: cards.filter(c => {
                        for (let e = c.parentElement; e; e = e.parentElement) {
                            if (getComputedStyle(e).overflowY === 'auto' &&
                                e.scrollHeight > e.clientHeight + 30) return true;
                        }
                        return false;
                    }).length,
                    review_tab_buttons: [...document.querySelectorAll('[role="tab"]')]
                        .filter(e => /reviews|리뷰/i.test(e.getAttribute('aria-label') || e.innerText || '')).length
                };
            }""")
            print("REVIEW_ENTRY_LAYOUT: " + json.dumps(initial_card_layout, sort_keys=True))
            # Compare initial deep-link cards with the explicit Reviews tab.
            # This probe is isolated from the crawler; the crawler reloads the URL.
            tabs = page.locator('[role="tab"]').filter(has_text="Reviews")
            if tabs.count() == 0:
                tabs = page.locator('[role="tab"]').filter(has_text="리뷰")
            if tabs.count():
                try:
                    tabs.first.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    tab_state = page.evaluate("""() => ({
                        cards: document.querySelectorAll('.jftiEf').length,
                        in_feed: [...document.querySelectorAll('.jftiEf')]
                            .filter(c => c.closest('[role="feed"]')).length,
                        selected_tabs: document.querySelectorAll('[role="tab"][aria-selected="true"]').length
                    })""")
                    print("REVIEW_TAB_OPEN_DIAGNOSTIC: " + json.dumps(tab_state, sort_keys=True))
                except Exception as exc:
                    print("REVIEW_TAB_OPEN_DIAGNOSTIC: " + json.dumps({
                        "error_type": type(exc).__name__
                    }))
            else:
                print('REVIEW_TAB_OPEN_DIAGNOSTIC: {"error_type":"tab_not_found"}')
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
            # Inspect network *metadata* only: status and request type, never
            # request bodies, URLs, cookies, review text, or account details.
            # Registered before a single controlled end-of-feed scroll.
            network_events = []
            def record_response(response):
                try:
                    request = response.request
                    if "google.com" not in response.url and "googleapis.com" not in response.url:
                        return
                    network_events.append({
                        "status": response.status,
                        "type": request.resource_type,
                        "method": request.method,
                    })
                except Exception:
                    pass
            page.on("response", record_response)
            try:
                # Select the nearest genuinely scrollable ancestor of a review card,
                # even when Google Maps does not expose role="feed".
                scroll_state = page.evaluate("""() => {
                    const card = document.querySelector('.jftiEf');
                    if (!card) return {found: false, reason: 'no_cards'};
                    let el = card.parentElement;
                    while (el) {
                        const style = getComputedStyle(el);
                        if (['auto', 'scroll'].includes(style.overflowY) &&
                            el.scrollHeight > el.clientHeight + 30) {
                            const before = el.scrollTop;
                            el.scrollTop = el.scrollHeight;
                            return {found: true, role_feed: el.getAttribute('role') === 'feed',
                                    moved: el.scrollTop > before,
                                    cards_before: document.querySelectorAll('.jftiEf').length};
                        }
                        el = el.parentElement;
                    }
                    return {found: false, reason: 'no_scrollable_ancestor'};
                }""")
                if scroll_state["found"]:
                    page.wait_for_timeout(3500)
                print("REVIEW_SCROLL_TARGET_DIAGNOSTIC: " + json.dumps(scroll_state, sort_keys=True))
                print("REVIEW_LOAD_NETWORK_DIAGNOSTIC: " + json.dumps({
                    "response_count": len(network_events),
                    "statuses": {str(code): sum(e["status"] == code for e in network_events)
                                 for code in sorted({e["status"] for e in network_events})},
                    "types": {kind: sum(e["type"] == kind for e in network_events)
                              for kind in sorted({e["type"] for e in network_events})},
                    "cards_after": page.locator(".jftiEf").count(),
                }, sort_keys=True))
            finally:
                page.remove_listener("response", record_response)
            # Never log review text, author, account data, or URLs from extracted reviews.
            print("NO_SORT_SMOKE_RESULT: " + json.dumps({
                "ok": result["ok"],
                "extracted_review_candidates": len(result["reviews"]),
                "error_type": result.get("collection_issue") or ("none" if result["ok"] else "other"),
                "database_writes": False,
                "full_coverage_verified": False,
            }, sort_keys=True))
            # A successful page load is not proof that the five-card ceiling
            # was overcome. Make this diagnostic fail visibly when it was not.
            observed = max(
                initial_panel["cards"],
                page.locator(".jftiEf").count(),
                len(result["reviews"]),
            )
            print("REVIEW_LOAD_VERDICT: " + json.dumps({
                "more_than_five_reviews_observed": observed > 5,
                "maximum_observed": observed,
                "full_coverage_verified": False,
            }, sort_keys=True))
            if not result["ok"]:
                raise SystemExit(2)
            if observed <= 5:
                raise SystemExit("REVIEW_LOAD_BLOCKED: five-card ceiling not overcome")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
