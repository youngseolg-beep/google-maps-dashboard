"""Local Windows-only diagnostic of the existing signed-in Chrome profile.

Read only: no DB, cookie export, screenshots, credentials, review text or raw
IDs in output. No sign-in automation, user-agent override, or challenge bypass.
Stops if Google asks for authentication or restricts the review list.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

STORE = "Saemaeul Central Eastville"
PLACE_URL = (
    "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/"
    "@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:"
    "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!"
    "16s%2Fg%2F11s674rmb9?entry=ttu"
)
PLACE_TOKEN = "0x484a32408c147d14"
REVIEW_TAB = re.compile(r"^(reviews|리뷰)(?:\s*\(?[\d,]+\)?)?$", re.I)
OVERVIEW_TAB = re.compile(r"^(overview|개요)$", re.I)
MAPS_HOME = "https://www.google.com/maps"
SEARCH_INPUT = (
    "input#searchboxinput, input[aria-label='Search Google Maps'], "
    "input[aria-label='Google 지도 검색'], input[aria-label='Google Maps 검색'], "
    "input[placeholder='Search Google Maps'], input[placeholder='Google 지도 검색']"
)


def page_summary(page):
    """Safe UI counts only; never include account names, review text or URLs."""
    return page.evaluate(r"""() => {
        const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        const nodes = [...document.querySelectorAll('[role="tab"], button, [role="button"]')]
            .filter(visible);
        const name = el => (el.innerText || '').trim().replace(/\s+/g, ' ');
        const tabs = nodes.filter(el => el.getAttribute('role') === 'tab');
        const tabKinds = tabs.map(el => ({
            kind: /^(overview|개요)$/i.test(name(el)) ? 'overview' :
                  /^(reviews|리뷰)(\s*\(?[\d,]+\)?)?$/i.test(name(el)) ? 'reviews' :
                  /^(menu|메뉴)$/i.test(name(el)) ? 'menu' :
                  /^(about|정보)$/i.test(name(el)) ? 'about' : 'other',
            selected: el.getAttribute('aria-selected') === 'true'
        }));
        return {
            visible_tabs: tabs.length,
            tab_kinds: tabKinds,
            overview_controls: nodes.filter(el => /^(overview|개요)(\s|$)/i.test(name(el))).length,
            reviews_controls: nodes.filter(el => /^(reviews|리뷰)(\s|$)/i.test(name(el))).length,
            visible_inputs: [...document.querySelectorAll('input')].filter(visible).length,
            visible_review_cards: [...document.querySelectorAll('.jftiEf[data-review-id]')]
                .filter(visible).length,
            place_heading: !!document.querySelector('h1.DUwDvf'),
            ready: document.readyState
        };
    }""")


def find_store_by_search(page, report):
    """Use normal visible Maps controls, with strict place identity verification."""
    report["phase"] = "open_maps_home"
    page.goto(MAPS_HOME, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    if blocked(page):
        return "ACCESS_RESTRICTED_STOPPED"

    # The current Korean Maps layout exposes the exact store in Recent.
    # This is the same ordinary navigation action as clicking a search result.
    exact_store = re.compile(
        r"^Saemaeul\s*(?:\(새마을식당\))?\s*[-–]?\s*Central Eastville$",
        re.I,
    )
    recent = page.get_by_text(exact_store).filter(visible=True)
    report["phase"] = "find_store_navigation"
    if recent.count() == 1:
        report["entry_method"] = "visible_exact_store"
        recent.first.click(timeout=5000)
    else:
        candidates = [
            page.locator(SEARCH_INPUT),
            page.get_by_role("combobox", name=re.compile(r"Google.*(지도|Maps)|검색|Search", re.I)),
            page.get_by_role("textbox", name=re.compile(r"Google.*(지도|Maps)|검색|Search", re.I)),
            page.locator("input[role='combobox'], input[type='search']"),
        ]
        search = None
        for candidate in candidates:
            visible = candidate.filter(visible=True)
            if visible.count() == 1:
                search = visible.first
                break
        if search is None:
            report["phase"] = "find_maps_search_input"
            return "SEARCH_CONTROL_NOT_VERIFIED"
        report["entry_method"] = "visible_search_input"
        report["phase"] = "search_store"
        search.fill(STORE)
        search.press("Enter")

    report["phase"] = "wait_for_expected_place"
    for _ in range(20):
        page.wait_for_timeout(1000)
        if blocked(page):
            return "ACCESS_RESTRICTED_STOPPED"
        if same_place(page.url):
            return None
        # Search results can require an explicit choice of the exact store.
        if report["entry_method"] == "visible_search_input":
            result = page.get_by_text(exact_store).filter(visible=True)
            if result.count() == 1:
                result.first.click(timeout=5000)
                report["entry_method"] = "search_then_exact_result"
    return "PLACE_NOT_VERIFIED"


def same_place(url):
    p = urlsplit(url)
    from urllib.parse import unquote
    path = unquote(p.path).lower()
    return (p.scheme == "https" and p.hostname in ("www.google.com", "google.com", "maps.google.com")
            and path.startswith("/maps/place/")
            and (PLACE_TOKEN in path or "/g/11s674rmb9" in path))


def result_status(count, blocked=False, scroll_verified=False):
    if blocked:
        return "ACCESS_RESTRICTED_STOPPED"
    if count >= 6 and scroll_verified:
        return "REVIEW_DEPTH_VERIFIED"
    return "REVIEW_DEPTH_UNVERIFIED"


def blocked(page):
    return page.evaluate("""() => {
        if (location.hostname === 'accounts.google.com' ||
            location.hostname === 'consent.google.com' ||
            location.pathname.startsWith('/sorry/')) return true;
        const visible = e => {
            const r=e.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        const dialogs = [...document.querySelectorAll('[role="dialog"],dialog')].filter(visible);
        return dialogs.some(e => /sign in|log in|로그인|verify it.s you|unusual traffic|captcha|본인 확인/i
            .test(e.innerText || ''));
    }""")


def find_visible_tab(page, pattern):
    """Match the rendered label, not a place-name-prefixed accessible label."""
    tabs = page.locator("[role='tab']").filter(visible=True)
    # Use exact displayed text first. Restrict to real tabs so review cards,
    # rating buttons, and Write a review controls cannot be clicked by mistake.
    match = tabs.filter(has_text=pattern)
    match.first.wait_for(state="visible", timeout=20000)
    if match.count() != 1:
        raise RuntimeError("AMBIGUOUS_TAB")
    return match.first


def selected(locator):
    return locator.get_attribute("aria-selected") == "true"


def observe(page, seen):
    # IDs are only used transiently to count distinct cards; no raw ID leaves
    # the process or enters the report.
    ids = page.locator(".jftiEf[data-review-id], [data-review-id].jftiEf").evaluate_all(
        "(cards) => cards.map(c => c.getAttribute('data-review-id')).filter(Boolean)"
    )
    for item in ids:
        seen.add(hashlib.sha256(item.encode("utf-8")).digest())
    return len(seen)


def review_pane(page):
    cards = page.locator(".jftiEf[data-review-id]")
    if cards.count() == 0:
        return None
    return cards.first.evaluate_handle("""card => {
        for (let el=card.parentElement; el && el!==document.body; el=el.parentElement) {
            const r=el.getBoundingClientRect(), css=getComputedStyle(el);
            if (r.width>0 && r.height>0 && ['auto','scroll'].includes(css.overflowY)
                && el.scrollHeight>el.clientHeight+30) return el;
        }
        return null;
    }""").as_element()


def coverage_status(count, expected, blocked=False):
    """Compare against the user-observed count, not proof of an API snapshot."""
    if blocked:
        return "ACCESS_RESTRICTED_STOPPED"
    if count == expected:
        return "EXPECTED_COUNT_MATCHED"
    if count > expected:
        return "EXPECTED_COUNT_EXCEEDED_RECHECK_TOTAL"
    return "EXPECTED_COUNT_NOT_REACHED"


def run_once(context, expected_total=None):
    report = {"status": "NOT_STARTED", "phase": "select_startup_tab",
              "overview_selected": False,
              "reviews_selected": False, "initial_unique": 0,
              "observed_unique": 0, "scroll_rounds": 0,
              "scroll_verified": False, "database_writes": False,
              "full_coverage_verified": False}
    if expected_total is not None:
        report["expected_total_user_observed"] = expected_total
        report["additional_unique"] = 0
        report["stop_reason"] = None
    page = None
    seen = set()
    # Track lifecycle events without recording URLs or other browser data.
    lifecycle = {"context_closed": False, "page_closed": False, "page_crashed": False}
    report["lifecycle"] = lifecycle
    try:
        context.on("close", lambda *_: lifecycle.update(context_closed=True))
        startup_tabs = [tab for tab in context.pages if not tab.is_closed()]
        report["startup_tab_count"] = len(startup_tabs)
        # A persistent context normally opens its own initial page. Reuse it
        # rather than opening a second tab while Chrome is still initializing.
        page = startup_tabs[0] if startup_tabs else context.new_page()
        page.on("close", lambda *_: lifecycle.update(page_closed=True))
        page.on("crash", lambda *_: lifecycle.update(page_crashed=True))
        failure = find_store_by_search(page, report)
        if failure:
            report["status"] = failure
            return report

        report["phase"] = "find_overview_tab"
        overview = find_visible_tab(page, OVERVIEW_TAB)
        report["phase"] = "find_reviews_tab"
        reviews = find_visible_tab(page, REVIEW_TAB)
        report["phase"] = "select_overview"
        if not selected(overview):
            overview.click(timeout=5000)
            page.wait_for_timeout(1500)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        report["overview_selected"] = selected(overview)
        if not report["overview_selected"] or not same_place(page.url):
            report["status"] = "OVERVIEW_NOT_VERIFIED"
            return report

        report["phase"] = "select_reviews"
        reviews.click(timeout=5000)
        page.wait_for_timeout(3000)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        report["reviews_selected"] = selected(reviews)
        if not report["reviews_selected"] or not same_place(page.url):
            report["status"] = "REVIEWS_NOT_VERIFIED"
            return report

        report["phase"] = "wait_for_review_cards"
        try:
            page.locator(".jftiEf[data-review-id]").first.wait_for(state="visible", timeout=12000)
        except Exception as exc:
            if type(exc).__name__ != "TimeoutError":
                raise
            report["status"] = result_status(0, blocked(page))
            return report

        report["phase"] = "observe_initial_reviews"
        report["initial_unique"] = observe(page, seen)
        report["observed_unique"] = len(seen)
        # Count IDs only in memory. Do not extract or save review contents.
        # The count check is bounded and never circumvents a restriction.
        idle = 0
        report["phase"] = "scroll_review_pane"
        max_rounds = 240 if expected_total is not None else 8
        for i in range(1, max_rounds + 1):
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if not same_place(page.url) or not selected(reviews):
                report["status"] = "REVIEW_CONTEXT_LOST"
                return report
            pane = review_pane(page)
            if pane is None:
                if expected_total is not None:
                    report["stop_reason"] = "NO_REVIEW_SCROLL_PANE"
                break
            box = pane.bounding_box()
            if not box:
                if expected_total is not None:
                    report["stop_reason"] = "NO_REVIEW_PANE_BOUNDS"
                break
            # Use the ordinary visible review list and normal mouse scrolling.
            before_top = pane.evaluate("(el) => el.scrollTop")
            before = len(seen)
            page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(1800)
            report["scroll_rounds"] = i
            report["observed_unique"] = observe(page, seen)
            after_pane = review_pane(page)
            after_top = after_pane.evaluate("(el) => el.scrollTop") if after_pane else before_top
            advanced = after_top > before_top or len(seen) > before
            report["scroll_verified"] = report["scroll_verified"] or advanced
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if expected_total is not None:
                report["additional_unique"] = len(seen) - report["initial_unique"]
                if len(seen) > before or i % 5 == 0:
                    print("LOCAL_REVIEW_PROGRESS: " + json.dumps({
                        "round": i, "observed_unique": len(seen),
                        "expected_total_user_observed": expected_total,
                    }), flush=True)
                if len(seen) >= expected_total:
                    report["stop_reason"] = "EXPECTED_TOTAL_REACHED"
                    break
            elif len(seen) >= 6 and report["scroll_verified"]:
                break
            idle = 0 if advanced else idle + 1
            if idle >= (4 if expected_total is not None else 3):
                if expected_total is not None:
                    report["stop_reason"] = "NO_FURTHER_SCROLL_OR_NEW_IDS"
                break

        report["phase"] = "final_depth_check"
        if expected_total is not None:
            report["stop_reason"] = report["stop_reason"] or "ROUND_LIMIT"
            report["status"] = coverage_status(len(seen), expected_total, blocked(page))
            report["expected_count_matched"] = report["status"] == "EXPECTED_COUNT_MATCHED"
        else:
            report["status"] = result_status(
                len(seen), blocked(page), report["scroll_verified"]
            )
        return report
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["status"] = (
            "BROWSER_CONNECTION_LOST"
            if report["error_type"] == "TargetClosedError" else "PROBE_ERROR"
        )
        return report
    finally:
        if page is not None and not page.is_closed():
            try:
                report["ui_summary"] = page_summary(page)
            except Exception:
                pass


def self_test():
    assert same_place(PLACE_URL)
    assert not same_place("https://example.com/maps/place/" + PLACE_TOKEN)
    assert not same_place("https://www.google.com/maps/search/" + PLACE_TOKEN)
    assert not same_place("https://www.google.com/maps/place/other")
    assert REVIEW_TAB.fullmatch("리뷰")
    assert REVIEW_TAB.fullmatch("Reviews")
    assert not REVIEW_TAB.fullmatch("Write a review")
    assert OVERVIEW_TAB.fullmatch("개요")
    assert not OVERVIEW_TAB.fullmatch("매장 개요 보기")
    assert not REVIEW_TAB.fullmatch("리뷰 작성")
    assert REVIEW_TAB.fullmatch("리뷰 (167)")
    assert result_status(5, scroll_verified=True) == "REVIEW_DEPTH_UNVERIFIED"
    assert result_status(6) == "REVIEW_DEPTH_UNVERIFIED"
    assert result_status(6, scroll_verified=True) == "REVIEW_DEPTH_VERIFIED"
    assert result_status(20, True, True) == "ACCESS_RESTRICTED_STOPPED"
    assert coverage_status(167, 167) == "EXPECTED_COUNT_MATCHED"
    assert coverage_status(166, 167) == "EXPECTED_COUNT_NOT_REACHED"
    assert coverage_status(168, 167) == "EXPECTED_COUNT_EXCEEDED_RECHECK_TOTAL"
    assert coverage_status(167, 167, True) == "ACCESS_RESTRICTED_STOPPED"
    print("SELF_TEST_PASS: 19 checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--inspect-on-failure", action="store_true",
                        help="Keep the visible Chrome window open after a failed check until Enter.")
    parser.add_argument("--expected-total", type=int,
                        help="Single read-only count comparison against the number seen in Maps.")
    args = parser.parse_args()
    if args.expected_total is not None and not 1 <= args.expected_total <= 1000:
        parser.error("--expected-total must be between 1 and 1000")
    if args.self_test:
        self_test()
        return 0
    if os.name != "nt":
        print("WINDOWS_ONLY")
        return 2
    profile = Path(os.environ["LOCALAPPDATA"]) / "SVReviewMaster" / "GoogleMapsSortProfile"
    if not (profile / "Default" / "Network" / "Cookies").is_file():
        print("DEDICATED_PROFILE_NOT_FOUND")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("PLAYWRIGHT_NOT_INSTALLED")
        return 2

    reports = []
    # No export or import of cookies, no synthetic browser identity. Each
    # trial opens and closes the existing dedicated local Chrome normally.
    target_runs = 1 if args.expected_total is not None else 3
    success_status = "EXPECTED_COUNT_MATCHED" if args.expected_total is not None else "REVIEW_DEPTH_VERIFIED"
    for attempt in range(1, target_runs + 1):
        context = None
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                )
                try:
                    report = run_once(context, args.expected_total)
                    # Snapshot unexpected lifecycle events BEFORE our intentional
                    # cleanup, so closing Chrome normally is not a false failure.
                    report["lifecycle"] = dict(report["lifecycle"])
                    if args.inspect_on_failure and report["status"] != success_status:
                        print("LOCAL_REVIEW_INSPECT: " + json.dumps(report, ensure_ascii=False), flush=True)
                        print("CHECK THE OPEN CHROME WINDOW. Press Enter in PowerShell to close it.", flush=True)
                        try:
                            input()
                        except EOFError:
                            pass
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
        except Exception as exc:
            report = {"status": "BROWSER_START_OR_CLOSE_ERROR",
                      "error_type": type(exc).__name__, "database_writes": False}
        report["attempt"] = attempt
        reports.append(report)
        print("LOCAL_REVIEW_PROBE: " + json.dumps(report, ensure_ascii=False), flush=True)
        if report["status"] != success_status:
            break
    passed = len(reports) == target_runs and all(r["status"] == success_status for r in reports)
    final_status = ("LOCAL_EXPECTED_COUNT_MATCHED" if passed else "LOCAL_COUNT_UNVERIFIED") if args.expected_total is not None else ("THREE_LOCAL_DEPTH_CHECKS_PASSED" if passed else "LOCAL_DEPTH_NOT_STABLE")
    print("LOCAL_REVIEW_FINAL: " + json.dumps({
        "status": final_status,
        "attempts": len(reports), "database_writes": False,
        "expected_total_user_observed": args.expected_total,
        "observed_unique": reports[-1].get("observed_unique", 0) if reports else 0,
        "full_coverage_verified": False,
    }), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
