"""Read-only Google Maps review-depth test with the existing dedicated login state.

Never expose or persist cookies, auth tokens, personal identity, review contents,
review identifiers, page HTML or request URLs. Never access Supabase.
"""
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from review_entry_matrix_probe import ORIGINAL

REPORT = Path("review-authenticated-depth-result.json")
OPTIONS = {
    "locale": "en-US", "timezone_id": "Asia/Seoul",
    "viewport": {"width": 1440, "height": 1000},
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}
FLAGS = [
    "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
    "--no-sandbox", "--disable-setuid-sandbox", "--lang=en-US,en",
]
MORE = re.compile(
    r"more reviews|see (all|more) reviews|view (all|more) reviews|"
    r"리뷰 더보기|모든 리뷰|전체 리뷰|meer recensies|semua ulasan", re.I
)


def get_auth_state():
    value = os.environ.get("GOOGLE_MAPS_STORAGE_STATE_B64", "").strip()
    if not value:
        return None, "AUTH_SECRET_NOT_CONFIGURED"
    try:
        state = json.loads(base64.b64decode(value, validate=True))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            return None, "AUTH_STATE_INVALID"
        if not any(
            isinstance(c, dict) and "google.com" in str(c.get("domain", ""))
            for c in state["cookies"]
        ):
            return None, "AUTH_STATE_NO_GOOGLE_COOKIES"
        return state, "AUTH_STATE_PARSED"
    except Exception:
        # Do not print exception strings: never disclose sensitive state.
        return None, "AUTH_STATE_INVALID"


def snapshot(page, seen):
    data = page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const dialogs = [...document.querySelectorAll('[role="dialog"]')]
            .filter(el => { const r=el.getBoundingClientRect(); return r.width>0&&r.height>0; });
        const dialogText = dialogs.map(el => (el.innerText || '').slice(0,1500))
            .join(' ').toLowerCase();
        const path = location.pathname;
        return {
            page_kind: path.includes('/maps/place/') ? 'place'
                : path.includes('/maps') ? 'other_maps' : 'non_maps',
            cards: cards.length,
            account_ui: !!document.querySelector(
                "a[aria-label^='Google Account'], button[aria-label^='Google Account'], " +
                "a[aria-label^='Google 계정'], button[aria-label^='Google 계정'], " +
                "a[href*='SignOutOptions'], a[href*='AccountChooser']"
            ),
            login_dialog: /sign in|log in|로그인|เข้าสู่ระบบ/.test(dialogText),
            review_feed_count: [...document.querySelectorAll('[role="feed"]')]
                .filter(el=>el.querySelector('.jftiEf')).length,
            keys: cards.map(el=>el.getAttribute('data-review-id')
                || (el.innerText||'').slice(0,2000)).filter(Boolean)
        };
    }""")
    for key in data.pop("keys"):
        seen.add(hashlib.sha256(key.encode("utf-8")).hexdigest())
    data["unique_seen"] = len(seen)
    return data


def safe_more_control(page):
    # Only named "more reviews" actions outside individual cards, never
    # a generic link, personal account link or login button.
    selector = "button, [role='button'], a[href]"
    item = page.evaluate("""(sel) => {
        const rx = /more reviews|see (all|more) reviews|view (all|more) reviews|리뷰 더보기|모든 리뷰|전체 리뷰|meer recensies|semua ulasan/i;
        const nodes = [...document.querySelectorAll(sel)];
        for (let i=0;i<nodes.length;i++) {
            const el=nodes[i], box=el.getBoundingClientRect();
            if (!box.width||!box.height||el.closest('.jftiEf,[data-review-id]')) continue;
            const label=(el.getAttribute('aria-label')||'')+' '+(el.innerText||'').slice(0,140);
            if (!rx.test(label)) continue;
            const href=el.getAttribute('href')||'';
            if (href && /^https?:\\/\\//i.test(href)
                && !/^https?:\\/\\/(www\\.)?google\\.[^/]+\\/maps\\//i.test(href)) continue;
            return i;
        }
        return null;
    }""", selector)
    if item is None:
        return "NOT_FOUND"
    try:
        page.locator(selector).nth(item).click(timeout=4500)
        page.wait_for_timeout(3000)
        return "CLICKED"
    except Exception:
        return "CLICK_ERROR"


def get_pane(page):
    if not page.locator(".jftiEf").count():
        return None
    handle = page.locator(".jftiEf").first.evaluate_handle("""card => {
        for(let el=card.parentElement;el;el=el.parentElement) {
            const css=getComputedStyle(el), r=el.getBoundingClientRect();
            if(r.width>0&&r.height>0&&['auto','scroll'].includes(css.overflowY)
                && el.scrollHeight>el.clientHeight+30) return el;
        }
        return null;
    }""")
    return handle.as_element()


def run(browser, name, state):
    options = dict(OPTIONS)
    if state is not None:
        options["storage_state"] = state
    context = browser.new_context(**options)
    context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    page = context.new_page()
    page.set_default_timeout(9000)
    seen = set()
    output = {
        "arm": name, "status": "STARTED", "states": [],
        "more_control": "NOT_TESTED", "scroll_rounds": 0,
    }
    try:
        page.goto(ORIGINAL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        output["states"].append({"stage":"initial", **snapshot(page, seen)})
        output["more_control"] = safe_more_control(page)
        after = snapshot(page, seen)
        output["states"].append({"stage":"after_more", **after})
        if after["login_dialog"]:
            output["status"] = "LOGIN_PROMPT_VISIBLE"
        elif after["unique_seen"] >= 6:
            output["status"] = "SIX_PLUS_OBSERVED"
        elif after["page_kind"] != "place":
            output["status"] = "LEFT_MAPS"
        else:
            pane = get_pane(page)
            if pane is None:
                output["status"] = "NO_REVIEW_SCROLL_PANE"
            else:
                pane.evaluate("(el)=>{el.scrollTop=0}")
                page.wait_for_timeout(600)
                for i in range(10):
                    rect=pane.bounding_box()
                    if not rect:
                        output["status"] = "PANE_NOT_VISIBLE"
                        break
                    page.mouse.move(
                        rect["x"] + rect["width"]/2, rect["y"]+rect["height"]/2
                    )
                    page.mouse.wheel(0,700)
                    page.wait_for_timeout(1300)
                    state_now=snapshot(page, seen)
                    output["states"].append({
                        "stage":"wheel_"+str(i+1), **state_now
                    })
                    output["scroll_rounds"] += 1
                    if len(seen)>=6:
                        output["status"] = "SIX_PLUS_OBSERVED"
                        break
                if output["status"] == "STARTED":
                    output["status"] = "BELOW_SIX"
    except Exception as exc:
        output["status"] = "EXECUTION_ERROR"
        output["error_type"] = type(exc).__name__
    finally:
        output["unique_seen"] = len(seen)
        context.close()
    return output


def main():
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("AUTH_PROBE_REFUSES_DATABASE_CREDENTIALS")
    auth_state, preflight = get_auth_state()
    result = {
        "preflight": preflight,
        "database_writes": False,
        "six_plus_authenticated": False,
        "runs": [],
    }
    if auth_state is not None:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True, args=FLAGS)
            try:
                result["runs"].append(run(browser,"anonymous",None))
                result["runs"].append(run(browser,"dedicated_login_state",auth_state))
                result["six_plus_authenticated"] = (
                    result["runs"][1]["status"] == "SIX_PLUS_OBSERVED"
                )
            finally:
                browser.close()

    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    summary = {
        "preflight": preflight,
        "six_plus_authenticated": result["six_plus_authenticated"],
        "runs": [{
            "arm": r["arm"], "status": r["status"],
            "unique": r["unique_seen"],
            "more_control": r["more_control"],
            "login_prompt": next(
                (x["login_dialog"] for x in r["states"] if x["stage"]=="after_more"),
                None
            ),
            "account_ui": next(
                (x["account_ui"] for x in r["states"] if x["stage"]=="after_more"),
                None
            ),
        } for r in result["runs"]]
    }
    print("AUTHENTICATED_REVIEW_DEPTH_VERDICT: "+json.dumps(summary))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Dedicated Google account read-only review depth\n\n")
            f.write("Preflight: **"+preflight+"**\n\n")
            f.write("| State | Unique cards | Outcome |\n|---|---:|---|\n")
            for r in result["runs"]:
                f.write(
                    "| "+r["arm"]+" | "+str(r["unique_seen"])+
                    " | "+r["status"]+" |\n"
                )
            f.write("\nNo auth data, account identity, review text or DB writes.\n")
    if not result["six_plus_authenticated"]:
        sys.exit(2)


if __name__=="__main__":
    main()
