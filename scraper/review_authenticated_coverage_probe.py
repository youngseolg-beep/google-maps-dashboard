"""Authenticated full-list depth/scroll test for one Google Maps store.

Uses the existing dedicated Google account state. Read-only:
- no Supabase credentials, writes or database comparisons
- no persisted review text, author names, IDs, cookies, URLs, screenshots
- only anonymized counts, page-state flags and scrolling diagnostics
- confirms cumulative unique cards, not full collection/completeness by itself
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Error as PlaywrightError
from review_authenticated_depth_probe import (
    FLAGS, OPTIONS, get_auth_state, normalize_storage_state_for_runner,
    safe_more_control, get_pane, snapshot as auth_snapshot,
)
from review_entry_matrix_probe import ORIGINAL
from review_multistore_probe import raw_snapshot, parse_count_candidates

OUT = Path("review-authenticated-coverage-result.json")
MAX_ROUNDS = 150
STALL_LIMIT = 5
SCROLL_PIXELS = 1200


def sample(page, known):
    raw = raw_snapshot(page)
    identities = raw.pop("ephemeral_keys", [])
    for ephemeral in identities:
        known.add(hashlib.sha256(ephemeral.encode("utf-8")).hexdigest())
    counts = parse_count_candidates(raw.pop("count_candidates", []))
    return {
        "unique_seen": len(known),
        "visible_cards": raw["visible_cards"],
        "review_feed_count": raw["review_feeds"],
        "review_tab_selected": raw["review_tab_selected"],
        "page_kind": raw["page_kind"],
        "ui_total_status": counts["status"],
        "ui_total": counts["displayed_total"],
    }


def scroll_values(pane):
    return pane.evaluate("""(e) => ({
        top: Math.round(e.scrollTop),
        range: Math.round(e.scrollHeight - e.clientHeight),
        viewport: Math.round(e.clientHeight)
    })""")



def final_dom_audit(page):
    """Review-card identity audit: counts only, never author/text/IDs."""
    return page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const candidates = cards.map(c => ({
            reviewId: c.getAttribute('data-review-id'),
            nestedId: c.querySelector('[data-review-id]')?.getAttribute('data-review-id') || null,
            hasRating: !!c.querySelector('[aria-label*="star"], [aria-label*="Star"], .kvMYJc'),
            hasAuthor: !!c.querySelector('.d4r55, .TSUbDb')
        }));
        const ids = candidates.map(c => c.reviewId || c.nestedId).filter(Boolean);
        const rx = /reviews?|리뷰|recensies|beoordelingen|ulasan|評論|ความคิดเห็น|đánh giá/i;
        const possible = [];
        for (const el of document.querySelectorAll('[aria-label], [role="tab"], button')) {
            if (el.closest('.jftiEf, [role="radio"]')) continue;
            const rect = el.getBoundingClientRect();
            if (!(rect.width > 0 && rect.height > 0)) continue;
            const content = [el.getAttribute('aria-label') || '', (el.innerText || '').slice(0, 150)];
            for (const label of content) {
                if (label.length > 160 || !rx.test(label)) continue;
                const m = label.match(/(?:reviews?|리뷰|評論|recensies|beoordelingen)\\s*\\(?\\s*(\\d[\\d,]*)|(?:\\d[\\d,]*)\\s*(?:reviews?|리뷰|評論|recensies|beoordelingen)/i);
                if (!m) continue;
                const n = Number((m[1] || (label.match(/\\d[\\d,]*/) || [''])[0]).replace(/,/g,''));
                if (Number.isSafeInteger(n) && n >= 6 && n <= 1000000) possible.push(n);
            }
        }
        return {
            review_cards: cards.length,
            explicit_id_cards: ids.length,
            explicit_unique_ids: new Set(ids).size,
            explicit_id_duplicate_count: ids.length - new Set(ids).size,
            cards_with_rating_indicator: candidates.filter(c => c.hasRating).length,
            cards_with_author_element: candidates.filter(c => c.hasAuthor).length,
            ui_count_candidates: [...new Set(possible)].sort((a,b)=>a-b).slice(0,20)
        };
    }""")

def main():
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("READ_ONLY_PROBE_REFUSES_DATABASE_SECRETS")
    state, preflight = get_auth_state()
    output = {
        "store": "Saemaeul Central Eastville",
        "preflight": preflight,
        "database_writes": False,
        "auth_secret_output": False,
        "full_coverage_verified": False,
        "status": "AUTH_UNAVAILABLE",
        "steps": [],
        "scroll_rounds": 0,
        "max_unique": 0,
        "network": {"fetch_xhr_responses": 0, "http_4xx": 0, "http_5xx": 0},
    }
    if state is None:
        write_result(output)
        sys.exit(2)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=FLAGS)
        context = None
        try:
            usable, compatibility = normalize_storage_state_for_runner(
                browser, state
            )
            output["auth_cookie_compatibility"] = compatibility
            if usable is None:
                output["status"] = "NO_COMPATIBLE_GOOGLE_COOKIES"
            else:
                context = browser.new_context(storage_state=usable, **OPTIONS)
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
                page = context.new_page()
                page.set_default_timeout(10000)
                monitor = {"enabled": False}

                def network(response):
                    if not monitor["enabled"]:
                        return
                    try:
                        if not ("google.com" in response.url or "googleapis.com" in response.url):
                            return
                        if response.request.resource_type in ("fetch", "xhr"):
                            output["network"]["fetch_xhr_responses"] += 1
                            if 400 <= response.status < 500:
                                output["network"]["http_4xx"] += 1
                            elif 500 <= response.status < 600:
                                output["network"]["http_5xx"] += 1
                    except Exception:
                        pass

                page.on("response", network)
                seen = set()
                try:
                    page.goto(
                        ORIGINAL, wait_until="domcontentloaded", timeout=45000
                    )
                    page.wait_for_timeout(5500)
                    initial = sample(page, seen)
                    output["steps"].append({"stage": "initial", **initial})

                    output["more_control_action"] = safe_more_control(page)
                    after = sample(page, seen)
                    output["steps"].append({"stage": "after_full_reviews_action", **after})
                    auth = auth_snapshot(page, set())
                    output["auth_account_ui"] = auth["account_ui"]
                    output["auth_login_dialog"] = auth["login_dialog"]

                    if auth["login_dialog"]:
                        output["status"] = "LOGIN_PROMPT_VISIBLE"
                    elif not auth["account_ui"]:
                        output["status"] = "GOOGLE_AUTH_NOT_CONFIRMED"
                    elif after["page_kind"] != "place":
                        output["status"] = "LEFT_MAPS_PLACE"
                    elif after["visible_cards"] == 0:
                        output["status"] = "REVIEW_CARDS_NOT_LOADED"
                    else:
                        pane = get_pane(page)
                        if pane is None:
                            output["status"] = "SCROLL_PANE_UNAVAILABLE"
                        else:
                            output["status"] = "SCROLLING"
                            pane.evaluate("(el)=>{el.scrollTop=0}")
                            page.wait_for_timeout(600)
                            before = sample(page, seen)
                            output["steps"].append({
                                "stage": "scroll_start", **before
                            })
                            monitor["enabled"] = True
                            idle_rounds = 0
                            bottom_stall_checks = 0
                            max_total = after.get("ui_total")
                            for i in range(1, MAX_ROUNDS + 1):
                                prev_count = len(seen)
                                prev_scroll = scroll_values(pane)
                                box = pane.bounding_box()
                                if not box or box["width"] <= 0 or box["height"] <= 0:
                                    output["status"] = "SCROLL_PANE_NOT_VISIBLE"
                                    break
                                page.mouse.move(
                                    box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2
                                )
                                page.mouse.wheel(0, SCROLL_PIXELS)
                                page.wait_for_timeout(900)
                                current = scroll_values(pane)
                                if current["top"] <= prev_scroll["top"]:
                                    # Retest only the same identified review pane;
                                    # no unrelated controls or web endpoints.
                                    pane.evaluate(
                                        "(el,pixels)=>{el.scrollTop += pixels}",
                                        SCROLL_PIXELS
                                    )
                                    page.wait_for_timeout(900)
                                    current = scroll_values(pane)
                                snap = sample(page, seen)
                                output["scroll_rounds"] = i
                                if i <= 3 or i % 10 == 0 or len(seen) > prev_count:
                                    output["steps"].append({
                                        "stage": "scroll", "round": i, **snap,
                                        "scroll_top": current["top"],
                                        "scroll_range": current["range"],
                                    })
                                if max_total is None and snap["ui_total"] is not None:
                                    max_total = snap["ui_total"]
                                output["max_unique"] = len(seen)
                                if len(seen) > prev_count:
                                    idle_rounds = 0
                                else:
                                    idle_rounds += 1
                                if max_total and len(seen) >= max_total:
                                    output["status"] = "UI_COUNT_REACHED"
                                    break
                                # A batch of 10 cards may occupy thousands
                                # of pixels. Not seeing new cards while the
                                # viewport still moves is *not* a stall.
                                # Wait for async loading only at the real
                                # bottom of the currently loaded list.
                                at_bottom = current["top"] >= current["range"] - 4
                                if at_bottom and idle_rounds >= STALL_LIMIT:
                                    page.wait_for_timeout(2200)
                                    after_wait = sample(page, seen)
                                    newer_scroll = scroll_values(pane)
                                    output["steps"].append({
                                        "stage": "bottom_wait", "round": i,
                                        **after_wait,
                                        "scroll_top": newer_scroll["top"],
                                        "scroll_range": newer_scroll["range"],
                                    })
                                    output["max_unique"] = len(seen)
                                    if (len(seen) > prev_count
                                            or newer_scroll["range"] > current["range"]):
                                        bottom_stall_checks = 0
                                        idle_rounds = 0
                                    else:
                                        bottom_stall_checks += 1
                                    if bottom_stall_checks >= 2:
                                        output["status"] = "STALLED_AT_BOTTOM"
                                        break
                                elif current["top"] > prev_scroll["top"]:
                                    bottom_stall_checks = 0
                                elif idle_rounds >= 12:
                                    output["status"] = "SCROLL_POSITION_NOT_ADVANCING"
                                    break
                            else:
                                output["status"] = "MAX_SCROLL_ROUNDS_REACHED"
                finally:
                    output["max_unique"] = len(seen)
                    try:
                        output["final_dom_audit"] = final_dom_audit(page)
                    except Exception:
                        output["final_dom_audit"] = {"status": "AUDIT_UNAVAILABLE"}
                    page.remove_listener("response", network)
        except PlaywrightError:
            # Playwright errors can contain URLs, cookie values or account data.
            output["status"] = "PLAYWRIGHT_ERROR"
        except Exception as exc:
            output["status"] = "PROBE_ERROR"
            output["error_type"] = type(exc).__name__
        finally:
            if context:
                context.close()
            browser.close()

    # Reaching the Google Maps displayed count still requires identity and
    # collection completeness checks before representing it as complete.
    output["full_coverage_verified"] = False
    write_result(output)
    if output["max_unique"] < 6 or output["status"] in (
        "AUTH_UNAVAILABLE", "NO_COMPATIBLE_GOOGLE_COOKIES",
        "LOGIN_PROMPT_VISIBLE", "GOOGLE_AUTH_NOT_CONFIRMED",
        "PLAYWRIGHT_ERROR", "PROBE_ERROR"
    ):
        sys.exit(2)


def write_result(data):
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2),encoding="utf-8")
    compact = {
        "status": data["status"],
        "initial_unique": data["steps"][0]["unique_seen"] if data["steps"] else None,
        "after_more_unique": next((s["unique_seen"] for s in data["steps"]
            if s["stage"] == "after_full_reviews_action"), None),
        "max_unique": data["max_unique"],
        "scroll_rounds": data["scroll_rounds"],
        "more_control_action": data.get("more_control_action"),
        "account_ui": data.get("auth_account_ui"),
        "ui_totals": sorted({s["ui_total"] for s in data["steps"]
                             if s.get("ui_total") is not None}),
        "network": data["network"],
        "full_coverage_verified": data["full_coverage_verified"],
        "final_dom_audit": data.get("final_dom_audit"),
    }
    print("AUTHENTICATED_COVERAGE_VERDICT: "+json.dumps(compact))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a",encoding="utf-8") as f:
            f.write("## Dedicated Google account — Central Eastville review depth\n\n")
            f.write("| Field | Result |\n|---|---|\n")
            for field, value in compact.items():
                f.write("| "+field+" | "+str(value)+" |\n")
            f.write("\nDistinct cards observed, not full historical coverage or new DB rows. No Supabase writes.\n")


if __name__ == "__main__":
    main()
