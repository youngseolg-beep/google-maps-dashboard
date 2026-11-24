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
    "@13.8036867,100.6145723,17z/data=!4m7!3m6!1s0x30e29df2eeea54a1:"
    "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!"
    "16s%2Fg%2F11s674rmb9?entry=ttu"
)
PLACE_TOKEN = "0x484a32408c147d14"
REVIEW_TAB = re.compile(r"^(reviews|리뷰)(?:\s*\(?[\d,]+\)?)?$", re.I)
OVERVIEW_TAB = re.compile(r"^(overview|개요)$", re.I)


def same_place(url):
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname in ("www.google.com", "google.com", "maps.google.com")
            and p.path.startswith("/maps/place/") and PLACE_TOKEN in p.path.lower())


def result_status(count, blocked=False):
    if blocked:
        return "ACCESS_RESTRICTED_STOPPED"
    if count >= 6:
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


def run_once(context):
    report = {"status": "NOT_STARTED", "overview_selected": False,
              "reviews_selected": False, "initial_unique": 0,
              "observed_unique": 0, "scroll_rounds": 0,
              "database_writes": False, "full_coverage_verified": False}
    page = None
    seen = set()
    try:
        page = context.new_page()
        page.goto(PLACE_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        if not same_place(page.url):
            report["status"] = "PLACE_NOT_VERIFIED"
            return report

        overview = page.get_by_role("tab", name=OVERVIEW_TAB)
        reviews = page.get_by_role("tab", name=REVIEW_TAB)
        overview.first.wait_for(state="visible", timeout=20000)
        reviews.first.wait_for(state="visible", timeout=20000)
        if not selected(overview.first):
            overview.first.click(timeout=5000)
            page.wait_for_timeout(1500)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        report["overview_selected"] = selected(overview.first)
        if not report["overview_selected"] or not same_place(page.url):
            report["status"] = "OVERVIEW_NOT_VERIFIED"
            return report

        reviews.first.click(timeout=5000)
        page.wait_for_timeout(3000)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        report["reviews_selected"] = selected(reviews.first)
        if not report["reviews_selected"] or not same_place(page.url):
            report["status"] = "REVIEWS_NOT_VERIFIED"
            return report

        try:
            page.locator(".jftiEf[data-review-id]").first.wait_for(state="visible", timeout=12000)
        except Exception:
            report["status"] = result_status(0, blocked(page))
            return report

        report["initial_unique"] = observe(page, seen)
        report["observed_unique"] = len(seen)
        # This is a limited depth diagnostic, not bulk collection or proof
        # of full coverage. A visible authentication challenge ends the run.
        idle = 0
        for i in range(1, 9):
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if not same_place(page.url) or not selected(reviews.first):
                report["status"] = "REVIEW_CONTEXT_LOST"
                return report
            pane = review_pane(page)
            if pane is None:
                break
            box = pane.bounding_box()
            if not box:
                break
            # Use the ordinary visible review list and normal mouse scrolling.
            page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(1800)
            report["scroll_rounds"] = i
            before = len(seen)
            report["observed_unique"] = observe(page, seen)
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if len(seen) >= 6 and i >= 1:
                break
            idle = idle + 1 if len(seen) == before else 0
            if idle >= 3:
                break

        report["status"] = result_status(len(seen), blocked(page))
        return report
    except Exception as exc:
        report["status"] = "PROBE_ERROR"
        report["error_type"] = type(exc).__name__
        return report
    finally:
        if page is not None:
            try:
                page.close()
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
    assert result_status(5) == "REVIEW_DEPTH_UNVERIFIED"
    assert result_status(6) == "REVIEW_DEPTH_VERIFIED"
    assert result_status(20, True) == "ACCESS_RESTRICTED_STOPPED"
    print("SELF_TEST_PASS: 11 checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
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
    for attempt in range(1, 4):
        context = None
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                )
                try:
                    report = run_once(context)
                finally:
                    context.close()
        except Exception as exc:
            report = {"status": "BROWSER_START_OR_CLOSE_ERROR",
                      "error_type": type(exc).__name__, "database_writes": False}
        report["attempt"] = attempt
        reports.append(report)
        print("LOCAL_REVIEW_PROBE: " + json.dumps(report, ensure_ascii=False), flush=True)
        if report["status"] != "REVIEW_DEPTH_VERIFIED":
            break
    passed = len(reports) == 3 and all(r["status"] == "REVIEW_DEPTH_VERIFIED" for r in reports)
    print("LOCAL_REVIEW_FINAL: " + json.dumps({
        "status": "THREE_LOCAL_DEPTH_CHECKS_PASSED" if passed else "LOCAL_DEPTH_NOT_STABLE",
        "attempts": len(reports), "database_writes": False,
        "full_coverage_verified": False,
    }), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
