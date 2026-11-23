"""Read-only comparison: original Playwright browser vs native Chromium/Chrome.

Purpose: the user confirmed 6+ reviews in ordinary Chrome, while GitHub
Actions Chromium consistently sees only five across three stores.

Each arm starts a fresh browser and profile, uses the same official store URL,
clicks only the explicit Reviews tab and scrolls its actual review container.
No cookies from users, proxies, credentials, DB access, reviewer information,
raw network bodies, or screenshots are collected.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright
from review_entry_matrix_probe import ORIGINAL

OUTPUT = Path("review-browser-environment.json")
USER_AGENT_OLD = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
BASE_ARGS = [
    "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
    "--no-sandbox", "--disable-setuid-sandbox", "--lang=en-US,en",
]
NATIVE_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
CASES = (
    ("existing_settings", None, BASE_ARGS, True),
    ("native_chromium", None, NATIVE_ARGS, False),
    ("native_chrome_stable", "chrome", NATIVE_ARGS, False),
)


def sample(page, unique):
    raw = page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const tab = [...document.querySelectorAll('[role="tab"]')].find(el =>
            /reviews|리뷰|recensies|beoordelingen|ulasan/i.test(
                (el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')));
        const dialogVisible = [...document.querySelectorAll('[role="dialog"]')].some(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        const scrollable = [];
        for (let el = cards[0]?.parentElement, i = 0; el && i < 15; el = el.parentElement, i++) {
            const cs = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (rect.width && rect.height && ['auto','scroll'].includes(cs.overflowY) &&
                el.scrollHeight > el.clientHeight + 30)
                scrollable.push({
                    range: Math.round(el.scrollHeight - el.clientHeight),
                    top: Math.round(el.scrollTop)
                });
        }
        return {
            page_kind: location.pathname.includes('/maps/place/') ? 'place' :
                location.pathname.includes('/maps') ? 'other_maps' : 'non_maps',
            review_tab_present: !!tab,
            review_tab_selected: !!tab && tab.getAttribute('aria-selected') === 'true',
            visible_cards: cards.length,
            review_feed_count: [...document.querySelectorAll('[role="feed"]')]
                .filter(el => el.querySelector('.jftiEf')).length,
            visible_dialog_present: dialogVisible,
            scroll_pane: scrollable[0] || null,
            browser_major_version: (/Chrome\/(\d+)/.exec(navigator.userAgent) || [])[1] || null,
            ephemeral_ids: cards.map(c => c.getAttribute('data-review-id') ||
                (c.innerText || '').slice(0, 1800)).filter(Boolean)
        };
    }""")
    for value in raw.pop("ephemeral_ids"):
        unique.add(hashlib.sha256(value.encode("utf-8")).hexdigest())
    raw["cumulative_unique_reviews"] = len(unique)
    return raw


def scroll_pane(page):
    if page.locator(".jftiEf").count() == 0:
        return None
    handle = page.locator(".jftiEf").first.evaluate_handle("""card => {
        for (let el = card.parentElement; el; el = el.parentElement) {
            const cs = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && ['auto','scroll'].includes(cs.overflowY) &&
                el.scrollHeight > el.clientHeight + 30) return el;
        }
        return null;
    }""")
    return handle.as_element()


def run_case(playwright, name, channel, flags, existing):
    out = {
        "name": name, "status": "STARTED", "snapshots": [],
        "scroll_rounds": 0, "wheel_movement_rounds": 0,
        "xhr_fetch_during_scroll": 0, "database_writes": False,
        "spoofed_user_agent": existing,
        "webdriver_init_override": existing,
    }
    browser = None
    context = None
    seen = set()
    watch = False
    try:
        options = {"headless": True, "args": flags}
        if channel:
            options["channel"] = channel
        browser = playwright.chromium.launch(**options)
        ctx_settings = {
            "locale": "en-US", "timezone_id": "Asia/Seoul",
            "viewport": {"width": 1440, "height": 1000},
        }
        if existing:
            ctx_settings["user_agent"] = USER_AGENT_OLD
        context = browser.new_context(**ctx_settings)
        if existing:
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        page = context.new_page()
        page.set_default_timeout(10000)

        def network(response):
            if not watch:
                return
            try:
                if ("google.com" in response.url or "googleapis.com" in response.url) and (
                    response.request.resource_type in ("xhr", "fetch")
                ):
                    out["xhr_fetch_during_scroll"] += 1
            except Exception:
                pass

        page.on("response", network)
        page.goto(ORIGINAL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6500)
        before = sample(page, seen)
        out["snapshots"].append({"stage": "initial", **before})
        if before["page_kind"] != "place" or before["visible_cards"] == 0:
            out["status"] = "NO_REVIEW_CARDS_OR_PLACE"
            return out

        tab = page.get_by_role("tab", name=re.compile(
            r"reviews?|리뷰|recensies|beoordelingen|ulasan", re.I
        ))
        if tab.count():
            tab.first.click(timeout=4500)
            page.wait_for_timeout(2200)
        out["snapshots"].append({"stage": "after_tab", **sample(page, seen)})
        pane = scroll_pane(page)
        if pane is None:
            out["status"] = "NO_SCROLL_PANE"
            return out

        pane.evaluate("(el) => {el.scrollTop = 0}")
        page.wait_for_timeout(600)
        out["snapshots"].append({"stage": "top", **sample(page, seen)})
        watch = True

        for i in range(11):
            top = pane.evaluate("(el) => el.scrollTop")
            rect = pane.bounding_box()
            if not rect or rect["width"] < 1 or rect["height"] < 1:
                out["status"] = "PANE_NOT_VISIBLE"
                break
            page.mouse.move(rect["x"] + rect["width"] / 2,
                            rect["y"] + rect["height"] / 2)
            page.mouse.wheel(0, 680)
            page.wait_for_timeout(1350)
            if pane.evaluate("(el) => el.scrollTop") > top:
                out["wheel_movement_rounds"] += 1
            new = sample(page, seen)
            out["snapshots"].append({"stage": "wheel_" + str(i + 1), **new})
            out["scroll_rounds"] += 1
            if len(seen) >= 6:
                out["status"] = "SIX_PLUS_OBSERVED"
                break
            bottom = pane.evaluate(
                "(el) => el.scrollTop >= el.scrollHeight - el.clientHeight - 3"
            )
            if bottom and i >= 4:
                page.wait_for_timeout(1100)
                new = sample(page, seen)
                out["snapshots"].append({"stage": "bottom", **new})
                if len(seen) >= 6:
                    out["status"] = "SIX_PLUS_OBSERVED"
                break
        if out["status"] == "STARTED":
            out["status"] = "BELOW_SIX"
    except Exception as exc:
        out["status"] = "ERROR"
        out["error_type"] = type(exc).__name__
    finally:
        out["unique_reviews_seen"] = len(seen)
        if context:
            context.close()
        if browser:
            browser.close()
    return out


def main():
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("Refusing database credentials in read-only probe")

    with sync_playwright() as p:
        results = [run_case(p, *case) for case in CASES]
    report = {
        "store": "Saemaeul Central Eastville", "user_normal_chrome_six_plus": True,
        "database_writes": False,
        "experiments": results,
        "any_six_plus_in_actions": any(r["unique_reviews_seen"] >= 6 for r in results),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [
        {
            "name": r["name"], "status": r["status"],
            "unique": r["unique_reviews_seen"],
            "scroll_rounds": r["scroll_rounds"],
            "movement_rounds": r["wheel_movement_rounds"],
            "fetch_xhr": r["xhr_fetch_during_scroll"],
            "browser_major": (r.get("snapshots", [{}])[0].get("browser_major_version")),
            "initial_cards": (r.get("snapshots", [{}])[0].get("visible_cards")),
        } for r in results
    ]
    print("REVIEW_BROWSER_ENV_VERDICT: " + json.dumps(compact))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                "## Browser environment comparison (read-only)\n\n"
                "User's normal Chrome: >5 reviews reported; "
                "not independently reproduced by this CI job.\n\n"
                "| Mode | Browser major | Initial cards | Unique observed | Movement rounds | Fetch/XHR | Result |\n"
                "|---|---:|---:|---:|---:|---:|---|\n"
            )
            for x in compact:
                f.write(
                    f"| {x['name']} | {x['browser_major'] or 'N/A'} | "
                    f"{x['initial_cards'] or 0} | {x['unique']} | "
                    f"{x['movement_rounds']} | {x['fetch_xhr']} | {x['status']} |\n"
                )
            f.write("\nNo database access. More than 5 unique cards does not establish full coverage.\n")


if __name__ == "__main__":
    main()
