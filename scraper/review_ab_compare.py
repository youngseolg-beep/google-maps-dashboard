"""Read-only A/B of historical and current Google Maps review paths.

Never runs the database crawler. Same URL, browser, flags, locale, UA and viewport;
separate fresh browser contexts; aggregate metrics only.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = ("https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/"
       "@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:"
       "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!"
       "16s%2Fg%2F11s674rmb9?entry=ttu")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
ARGS = ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
        "--no-sandbox", "--disable-setuid-sandbox", "--lang=en-US,en"]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(page, unique):
    # Identifiers and text are transient and never written to logs/artifacts.
    data = page.evaluate("""() => {
        let cards = [];
        for (const sel of ['.jftiEf', "div[role='article']", 'div[data-review-id]']) {
            cards = [...document.querySelectorAll(sel)];
            if (cards.length) break;
        }
        const tab = [...document.querySelectorAll('[role="tab"]')].find(e =>
            /Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i.test(
                (e.getAttribute('aria-label') || '') + ' ' + (e.textContent || '')));
        const anc = [];
        for (let el = cards[0]?.parentElement, n = 0; el && n < 15; el = el.parentElement, n++) {
            if (el.scrollHeight > el.clientHeight + 30) {
                const box = el.getBoundingClientRect();
                anc.push({range: Math.round(el.scrollHeight - el.clientHeight),
                          top: Math.round(el.scrollTop), overflow: getComputedStyle(el).overflowY,
                          visible: box.width > 0 && box.height > 0});
            }
        }
        const dialogs = [...document.querySelectorAll('[role="dialog"]')]
            .filter(e => e.getClientRects().length > 0);
        const path = location.pathname;
        return {
            location_kind: path.includes('/maps/place/') ? 'place' :
                path.includes('/maps') ? 'other_maps' : 'non_maps',
            visible_cards: cards.length,
            feed_count: [...document.querySelectorAll('[role="feed"]')]
                .filter(e => e.querySelector('.jftiEf')).length,
            selected_reviews_tab: !!tab && tab.getAttribute('aria-selected') === 'true',
            visible_sign_in_dialog: dialogs.some(e => /sign in|log in|로그인/i.test(e.innerText || '')),
            scroll_ancestors: anc.slice(0, 2),
            keys: cards.map(c => (c.getAttribute('data-review-id') || '') ||
                                (c.innerText || '').slice(0, 1800)).filter(Boolean)
        };
    }""")
    for key in data.pop("keys"):
        unique.add(hashlib.sha256(key.encode("utf-8")).hexdigest())
    data["cumulative_unique"] = len(unique)
    return data


def run(browser, scraper, name, rounds=4):
    ctx = browser.new_context(user_agent=USER_AGENT, locale="en-US",
                              timezone_id="Asia/Seoul", viewport={"width": 1440, "height": 1000})
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = ctx.new_page()
    page.set_default_timeout(45000)
    unique = set()
    result = {"version": name, "stage": "setup", "states": {}, "scroll_attempts": 0,
              "xhr_fetch_responses": 0, "response_count": 0, "scroll_errors": []}

    def on_response(response):
        try:
            if "google.com" in response.url or "googleapis.com" in response.url:
                result["response_count"] += 1
                if response.request.resource_type in ("xhr", "fetch"):
                    result["xhr_fetch_responses"] += 1
        except Exception:
            pass

    page.on("response", on_response)
    try:
        result["stage"] = "open_page"
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        with contextlib.redirect_stdout(io.StringIO()):
            scraper.click_cookie_buttons(page)
        page.wait_for_timeout(4000)
        result["states"]["before_panel"] = inspect(page, unique)
        result["stage"] = "open_panel"
        with contextlib.redirect_stdout(io.StringIO()):
            result["panel_reported"] = bool(scraper.open_reviews_panel(page))
        page.wait_for_timeout(3500)
        result["states"]["after_panel"] = inspect(page, unique)
        result["stage"] = "scroll"
        for i in range(rounds):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    scraper.scroll_reviews(page)
                result["scroll_attempts"] += 1
            except Exception as exc:
                result["scroll_errors"].append(type(exc).__name__)
                break
            page.wait_for_timeout(1500)
            result["states"]["scroll_" + str(i + 1)] = inspect(page, unique)
        result["stage"] = "complete"
    except Exception as exc:
        result["stage"] = "error"
        result["error_type"] = type(exc).__name__
    finally:
        result["unique_review_candidates"] = len(unique)
        result["max_visible_cards"] = max(
            [s["visible_cards"] for s in result["states"].values()] or [0])
        page.remove_listener("response", on_response)
        ctx.close()
    return result


def judge(a, b):
    if a["stage"] == "error" or b["stage"] == "error":
        return "INCONCLUSIVE_EXECUTION_ERROR"
    av, bv = a["unique_review_candidates"], b["unique_review_candidates"]
    if av > 5 and bv <= 5:
        return "CURRENT_REGRESSION_SUSPECTED"
    if bv > 5 and av <= 5:
        return "CURRENT_BETTER"
    if av <= 5 and bv <= 5:
        return "BOTH_BLOCKED_AT_FIVE_OR_FEWER"
    return "BOTH_LOADED_MORE_THAN_FIVE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True)
    ap.add_argument("--current", required=True)
    a = ap.parse_args()
    if os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("A/B refuses to run with Supabase credentials")
    legacy, current = load("ab_legacy", a.legacy), load("ab_current", a.current)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=ARGS)
        try:
            left = run(browser, legacy, "legacy_aug05")
            right = run(browser, current, "current_test")
        finally:
            browser.close()
    report = {
        "baseline_commit": "9e4f685d3edf331aabfb0af9c15a49ac8859cf90",
        "baseline_proven_good": False,
        "candidate_commit": os.getenv("GITHUB_SHA", "local"),
        "store": "Saemaeul Central Eastville",
        "database_writes": False,
        "legacy": left, "current": right,
        "verdict": judge(left, right),
    }
    Path("review-ab-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REVIEW_AB_VERDICT: " + report["verdict"])
    print("REVIEW_AB_RESULT: " + json.dumps(report, ensure_ascii=False))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        def after(item):
            return item["states"].get("after_panel", {}).get("location_kind", "unknown")
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Read-only Google Maps A/B comparison\n\n"
                    "Legacy is Aug 5 snapshot, not confirmed last-working.\n\n"
                    "| Measure | Legacy Aug 5 | Current test |\n|---|---:|---:|\n"
                    f"| Distinct review candidates | {left['unique_review_candidates']} | {right['unique_review_candidates']} |\n"
                    f"| Max visible cards | {left['max_visible_cards']} | {right['max_visible_cards']} |\n"
                    f"| Page after panel click | {after(left)} | {after(right)} |\n"
                    f"| Fetch/XHR responses | {left['xhr_fetch_responses']} | {right['xhr_fetch_responses']} |\n"
                    f"| Stage | {left['stage']} | {right['stage']} |\n\n"
                    f"**Verdict: {report['verdict']}**\n\n"
                    "This does not validate DB writes or full review coverage.\n")


if __name__ == "__main__":
    main()
