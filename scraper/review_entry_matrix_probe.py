"""Read-only Google Maps entry-path matrix, independent from production scraper.

Check the same store through three URL variants, whether the Reviews tab is
already selected, the availability of explicit review-entry controls, and
whether small wheel scrolls load *new* review identities. Never access a DB.
No review text, author, review IDs, cookies, request URLs or screenshots logged.
"""
import hashlib
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ORIGINAL = (
    "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/"
    "@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:"
    "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!"
    "16s%2Fg%2F11s674rmb9?entry=ttu"
)
VARIANTS = (
    ("current_deep_link", ORIGINAL),
    ("without_review_marker", ORIGINAL.replace("!9m1!1b1", "")),
    ("place_path_only", ORIGINAL.split("/data=")[0]),
)
OPTIONS = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "locale": "en-US",
    "timezone_id": "Asia/Seoul",
    "viewport": {"width": 1440, "height": 1000},
}
REVIEW_TAB = r"Reviews|리뷰|Recensies|Beoordelingen|Ulasan"


def sample(page, known):
    state = page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const tabs = [...document.querySelectorAll('[role="tab"]')];
        const tab = tabs.find(e => /Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i.test(
            (e.getAttribute('aria-label') || '') + ' ' + (e.textContent || '')
        ));
        const scrolls = [];
        for (let e = cards[0]?.parentElement, i = 0; e && i < 15; e = e.parentElement, i++) {
            const css = getComputedStyle(e);
            if (e.scrollHeight > e.clientHeight + 30) {
                const box = e.getBoundingClientRect();
                scrolls.push({
                    depth: i, overflow: css.overflowY,
                    range: Math.round(e.scrollHeight - e.clientHeight),
                    top: Math.round(e.scrollTop),
                    visible: box.width > 0 && box.height > 0
                });
            }
        }
        const visible = node => {
            const box = node.getBoundingClientRect();
            return box.width > 0 && box.height > 0;
        };
        const isReviews = text => /Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i.test(text || '');
        const reviewButtons = [...document.querySelectorAll('button')].filter(b =>
            visible(b) && isReviews(b.getAttribute('aria-label') || '')).length;
        const moreReviewButtons = [...document.querySelectorAll('button')]
            .filter(b => visible(b) && (b.getAttribute('jsaction') || '').includes('pane.rating.moreReviews')).length;
        const hrefReviewLinks = [...document.querySelectorAll('a[href]')]
            .filter(a => visible(a) && /reviews|!9m1!1b1/i.test(a.getAttribute('href') || '')).length;
        const path = location.pathname;
        return {
            page_kind: path.includes('/maps/place/') ? 'place' :
                path.includes('/maps') ? 'other_maps' : 'non_maps',
            visible_cards: cards.length,
            selected_reviews_tab: !!tab && tab.getAttribute('aria-selected') === 'true',
            has_review_tab: !!tab,
            review_tab_controls_target: !!(tab?.getAttribute('aria-controls') &&
                document.getElementById(tab.getAttribute('aria-controls'))),
            review_feed: [...document.querySelectorAll('[role="feed"]')]
                .filter(e => e.querySelector('.jftiEf')).length,
            visible_review_labeled_buttons: reviewButtons,
            explicit_more_reviews_buttons: moreReviewButtons,
            visible_review_links: hrefReviewLinks,
            scrollable_ancestors: scrolls.slice(0, 3),
            // Transient values removed in Python before reporting.
            fingerprints: cards.map(c => c.getAttribute('data-review-id') ||
                (c.innerText || '').slice(0, 1800)).filter(Boolean)
        };
    }""")
    for identity in state.pop("fingerprints"):
        known.add(hashlib.sha256(identity.encode("utf-8")).hexdigest())
    state["unique_seen"] = len(known)
    return state


def run_one(browser, label, url):
    ctx = browser.new_context(**OPTIONS)
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = ctx.new_page()
    page.set_default_timeout(10000)
    seen = set()
    report = {"variant": label, "states": {}, "actions": [], "xhr_fetch_responses": 0}
    monitor = False

    def network(response):
        if not monitor:
            return
        try:
            if ("google.com" in response.url or "googleapis.com" in response.url) and (
                response.request.resource_type in ("xhr", "fetch")
            ):
                report["xhr_fetch_responses"] += 1
        except Exception:
            pass

    page.on("response", network)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        report["states"]["initial"] = sample(page, seen)

        # Explicit tab only: never click review hrefs or generic text.
        tabs = page.get_by_role("tab", name=__import__("re").compile(REVIEW_TAB, __import__("re").I))
        if tabs.count():
            try:
                tabs.first.click(timeout=4000)
                page.wait_for_timeout(2000)
                report["actions"].append("review_tab_clicked")
            except Exception as exc:
                report["actions"].append("review_tab_" + type(exc).__name__)
        else:
            report["actions"].append("review_tab_unavailable")
        report["states"]["after_tab"] = sample(page, seen)

        # Look for explicit Google Maps 'more reviews' action, not generic links.
        more = page.locator("button[jsaction*='pane.rating.moreReviews']")
        if more.count():
            try:
                more.first.click(timeout=3500)
                page.wait_for_timeout(2500)
                report["actions"].append("explicit_more_reviews_clicked")
            except Exception as exc:
                report["actions"].append("explicit_more_reviews_" + type(exc).__name__)
        else:
            report["actions"].append("explicit_more_reviews_unavailable")
        report["states"]["after_more_reviews"] = sample(page, seen)

        monitor = True
        # Reset and wheel in small increments; compare actual unique review
        # identities, not just visible card count in virtualized layouts.
        page.evaluate("""() => {
            const card = document.querySelector('.jftiEf');
            for (let el = card?.parentElement; el; el = el.parentElement) {
                if (['auto','scroll'].includes(getComputedStyle(el).overflowY) &&
                    el.scrollHeight > el.clientHeight + 30) {el.scrollTop = 0; break;}
            }
        }""")
        page.wait_for_timeout(600)
        report["states"]["scroll_top"] = sample(page, seen)
        for i in range(6):
            try:
                box = page.locator(".jftiEf").first.bounding_box(timeout=2000)
                if box:
                    page.mouse.move(
                        max(1, min(1350, box["x"] + min(box["width"] / 2, 100))),
                        max(1, min(900, box["y"] + 60)),
                    )
                page.mouse.wheel(0, 700)
                page.wait_for_timeout(1300)
                report["states"]["wheel_" + str(i + 1)] = sample(page, seen)
            except Exception as exc:
                report["actions"].append("wheel_" + type(exc).__name__)
                break
        report["max_unique"] = len(seen)
        report["max_visible"] = max(
            (v["visible_cards"] for v in report["states"].values()), default=0
        )
        report["completed"] = True
    except Exception as exc:
        report["completed"] = False
        report["error_type"] = type(exc).__name__
        report["max_unique"] = len(seen)
    finally:
        page.remove_listener("response", network)
        ctx.close()
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--only-current", action="store_true")
    args = parser.parse_args()
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("Refusing to run with Supabase credentials")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--lang=en-US,en",
            ],
        )
        try:
            variants = VARIANTS[:1] if args.only_current else VARIANTS
            reports = [run_one(browser, label, url) for label, url in variants]
        finally:
            browser.close()
    result = {
        "store": "Saemaeul Central Eastville",
        "database_writes": False,
        "browser_mode": "headed" if args.headed else "headless",
        "variants": reports,
        "any_over_five": any(r.get("max_unique", 0) > 5 for r in reports),
    }
    result_file = "review-entry-matrix-headed.json" if args.headed else "review-entry-matrix.json"
    Path(result_file).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("REVIEW_ENTRY_MATRIX_RESULT: " + json.dumps(result, ensure_ascii=False))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                "## Read-only Google Maps review entry matrix\n\n"
                "| Entry path | Initial cards | After tab | After moreReviews | Max distinct | Page after tab | Fetch/XHR |\n"
                "|---|---:|---:|---:|---:|---|---:|\n"
            )
            for r in reports:
                states = r["states"]
                f.write(
                    f"| {r['variant']} | {states.get('initial', {}).get('visible_cards', 0)}"
                    f" | {states.get('after_tab', {}).get('visible_cards', 0)}"
                    f" | {states.get('after_more_reviews', {}).get('visible_cards', 0)}"
                    f" | {r.get('max_unique', 0)}"
                    f" | {states.get('after_tab', {}).get('page_kind', 'unknown')}"
                    f" | {r['xhr_fetch_responses']} |\n"
                )
            f.write(
                f"\nMore than 5 unique observed: **{result['any_over_five']}**. "
                "Diagnostic only: no DB, no completeness claim.\n"
            )


if __name__ == "__main__":
    main()
