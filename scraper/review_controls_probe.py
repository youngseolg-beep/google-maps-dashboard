"""Classify review-related Google Maps controls and test safe ones in isolation.

Read-only. No Supabase credentials, review text, author names, URLs, screenshots,
cookies or raw HTML are logged/saved. Every click uses a fresh browser context.
"""
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = (
    "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/"
    "@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:"
    "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!"
    "16s%2Fg%2F11s674rmb9?entry=ttu"
)
ELEMENTS = "button, [role='button'], [role='tab'], a[href]"
CONTEXT = {
    "locale": "en-US",
    "timezone_id": "Asia/Seoul",
    "viewport": {"width": 1440, "height": 1000},
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}
# Deliberately exclude write/reply/login, external links, and card expansion.
SAFE_ACTIONS = {
    "review_tab", "review_count_entry", "all_reviews_action",
    "more_reviews_action", "review_link_internal",
}
MAX_CLICKS = 7


def classify_controls(page):
    """Return only allowlisted categories and DOM ordinals, never label text."""
    return page.evaluate("""(selector) => {
        const elems = [...document.querySelectorAll(selector)];
        const visible = e => {
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
        };
        const reviewTerm = /reviews?|리뷰|recensies|beoordelingen|ulasan/i;
        const isWrite = /write (a )?review|add (a )?review|리뷰 작성|review this place|rate (this|the)/i;
        const isSort = /sort|filter|정렬|필터|sorteer|urutan/i;
        const isAll = /all reviews|see (all|more) reviews|view (all|more) reviews|전체 리뷰|모든 리뷰/i;
        const hasCount = /\\b\\d[\\d,\\.]*\\s*(reviews?|recensies|beoordelingen|ulasan)\\b|리뷰\\s*\\d|\\d\\s*개의?\\s*리뷰/i;
        const out = [];
        elems.forEach((e, index) => {
            if (!visible(e)) return;
            const role = e.getAttribute('role') || e.tagName.toLowerCase();
            const tag = e.tagName.toLowerCase();
            const label = [
                e.getAttribute('aria-label') || '',
                e.getAttribute('title') || '',
                (e.innerText || '').slice(0, 120)
            ].join(' ');
            const action = e.getAttribute('jsaction') || '';
            const href = e.getAttribute('href') || '';
            const card = !!e.closest('.jftiEf, [data-review-id]');
            const hit = reviewTerm.test(label) || /moreReviews|review/i.test(action) ||
                        (tag === 'a' && /reviews|!9m1!1b1/i.test(href));
            if (!hit) return;
            let category;
            if (card) category = 'review_card_action';
            else if (isWrite.test(label)) category = 'write_review';
            else if (isSort.test(label)) category = 'sort_filter';
            else if (tag === 'a') category = /^https?:\\/\\//i.test(href) &&
                !/^https?:\\/\\/(www\\.)?google\\.[^/]+\\/maps\\//i.test(href) ?
                'external_review_link' : 'review_link_internal';
            else if (/pane\\.rating\\.moreReviews/i.test(action)) category = 'more_reviews_action';
            else if (role === 'tab') category = 'review_tab';
            else if (isAll.test(label)) category = 'all_reviews_action';
            else if (hasCount.test(label)) category = 'review_count_entry';
            else category = 'other_review_labeled_control';
            out.push({
                index, category, tag, role,
                disabled: e.hasAttribute('disabled') || e.getAttribute('aria-disabled') === 'true',
                selected: e.getAttribute('aria-selected') === 'true',
                in_review_card: card,
                href_kind: tag === 'a' ?
                    (/^https?:\\/\\//i.test(href) ? 'absolute' : 'relative') : 'none',
                action_kind: /pane\\.rating\\.moreReviews/i.test(action) ?
                    'moreReviews' : /review/i.test(action) ? 'other_review' : 'none'
            });
        });
        return out;
    }""", ELEMENTS)


def snapshot(page, seen):
    state = page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const path = location.pathname;
        const tabs = [...document.querySelectorAll('[role="tab"]')];
        const selected = tabs.some(e =>
            e.getAttribute('aria-selected') === 'true' &&
            /Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i.test(
                (e.getAttribute('aria-label') || '') + (e.textContent || '')));
        return {
            kind: path.includes('/maps/place/') ? 'place' :
                path.includes('/maps') ? 'other_maps' : 'non_maps',
            cards: cards.length, selected_reviews_tab: selected,
            feed: [...document.querySelectorAll('[role="feed"]')]
                .filter(f => f.querySelector('.jftiEf')).length,
            keys: cards.map(c => c.getAttribute('data-review-id') ||
                (c.innerText || '').slice(0, 1600)).filter(Boolean)
        };
    }""")
    for identity in state.pop("keys"):
        seen.add(hashlib.sha256(identity.encode("utf-8")).hexdigest())
    state["unique_seen"] = len(seen)
    return state


def new_page(browser):
    context = browser.new_context(**CONTEXT)
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    page = context.new_page()
    page.set_default_timeout(7000)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    return context, page


def test_one(browser, selected):
    result = {
        "category": selected["category"],
        "index": selected["index"],
        "clicked": False,
        "verified_same_control": False,
        "network_xhr_after": 0,
        "stage": "initializing"
    }
    ctx = None
    try:
        ctx, page = new_page(browser)
        seen = set()
        result["before"] = snapshot(page, seen)
        controls = {c["index"]: c for c in classify_controls(page)}
        current = controls.get(selected["index"])
        if not current or current["category"] != selected["category"] or current["disabled"]:
            result["stage"] = "control_changed_or_unavailable"
            return result
        result["verified_same_control"] = True

        def on_response(response):
            try:
                if ("google.com" in response.url or "googleapis.com" in response.url) and (
                    response.request.resource_type in ("xhr", "fetch")
                ):
                    result["network_xhr_after"] += 1
            except Exception:
                pass

        page.on("response", on_response)
        try:
            element = page.locator(ELEMENTS).nth(selected["index"])
            element.click(timeout=3500)
            result["clicked"] = True
            page.wait_for_timeout(2400)
            result["after_click"] = snapshot(page, seen)
            if result["after_click"]["kind"] != "place":
                result["stage"] = "left_place"
                return result
            # This is a test of the selected control, not a blind repeated click.
            for _ in range(3):
                if page.locator(".jftiEf").count() == 0:
                    break
                page.locator(".jftiEf").first.evaluate("""card => {
                    for (let e = card.parentElement; e; e = e.parentElement) {
                        const s = getComputedStyle(e);
                        if (['auto','scroll'].includes(s.overflowY) &&
                            e.scrollHeight > e.clientHeight + 30) {
                            e.scrollTop = Math.min(
                                e.scrollHeight, e.scrollTop + Math.max(e.clientHeight, 750));
                            break;
                        }
                    }
                }""")
                page.wait_for_timeout(1500)
            result["after_scroll"] = snapshot(page, seen)
            result["stage"] = "complete"
        finally:
            page.remove_listener("response", on_response)
    except Exception as exc:
        result["stage"] = "error"
        result["error_type"] = type(exc).__name__
    finally:
        if ctx is not None:
            ctx.close()
    return result


def select_candidates(controls):
    selected = []
    counts = Counter()
    for control in controls:
        category = control["category"]
        if (category not in SAFE_ACTIONS or control["disabled"] or
                counts[category] >= 2 or len(selected) >= MAX_CLICKS):
            continue
        selected.append(control)
        counts[category] += 1
    return selected


def main():
    if os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("Cannot run control probe with database credentials")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox",
                "--lang=en-US,en",
            ]
        )
        try:
            ctx, page = new_page(browser)
            try:
                controls = classify_controls(page)
                initial = snapshot(page, set())
            finally:
                ctx.close()
            candidates = select_candidates(controls)
            tests = [test_one(browser, c) for c in candidates]
        finally:
            browser.close()
    categories = dict(sorted(Counter(c["category"] for c in controls).items()))
    tested = [x for x in tests if x.get("verified_same_control")]
    max_unique = max(
        [initial["unique_seen"]] +
        [x.get("after_scroll", x.get("after_click", {})).get("unique_seen", 0) for x in tests]
    )
    report = {
        "store": "Saemaeul Central Eastville",
        "read_only": True,
        "database_writes": False,
        "category_counts": categories,
        "inventory": controls,
        "initial": initial,
        "selected_candidate_count": len(candidates),
        "tested_count": len(tested),
        "experiments": tests,
        "max_unique_observed": max_unique,
        "more_than_five_observed": max_unique > 5,
        "full_coverage_verified": False
    }
    Path("review-controls-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("REVIEW_CONTROLS_SUMMARY: " + json.dumps({
        "category_counts": categories,
        "candidate_count": len(candidates),
        "tested_count": len(tested),
        "max_unique": max_unique,
        "over_five": max_unique > 5,
        "experiments": [
            {"category": e["category"], "stage": e["stage"],
             "before": e.get("before", {}).get("unique_seen", 0),
             "after": e.get("after_scroll", e.get("after_click", {})).get("unique_seen", 0),
             "page_kind": e.get("after_click", {}).get("kind", "unknown")}
            for e in tests
        ]
    }, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(
                "## Review-related controls: read-only classification\n\n"
                "| Control category | Visible count |\n|---|---:|\n"
            )
            for key, count in categories.items():
                f.write("| " + key + " | " + str(count) + " |\n")
            f.write("\n| Tested category | Outcome | Unique before | Unique after | Page |\n"
                    "|---|---|---:|---:|---|\n")
            for e in tests:
                after = e.get("after_scroll", e.get("after_click", {}))
                f.write(
                    "| " + e["category"] + " | " + e["stage"]
                    + " | " + str(e.get("before", {}).get("unique_seen", 0))
                    + " | " + str(after.get("unique_seen", 0))
                    + " | " + e.get("after_click", {}).get("kind", "unknown") + " |\n"
                )
            f.write("\nNo database access. Reviewer details not collected in reports.\n")


if __name__ == "__main__":
    main()
