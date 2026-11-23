"""Read-only cross-store review-count and 6+ unique-review loading verification.

The three store URLs originate in this repository:
- Central Eastville: scraper/review_entry_matrix_probe.py (verified diagnostics)
- Bornga Dunhua South and Saemaeul Seoul St.: index.html STORE_URL_MAP

This probe never fetches Supabase, saves review content, or changes crawler code.
An unverified Maps page / missing total count must be reported as UNKNOWN,
not as 0 reviews. The result counts distinct cards seen across scroll rounds,
not necessarily *new since last crawl* or complete review coverage.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright
from review_entry_matrix_probe import ORIGINAL as CENTRAL_EASTVILLE_URL

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path("review-multistore-verification.json")
CONTEXT = {
    "locale": "en-US",
    "timezone_id": "Asia/Seoul",
    "viewport": {"width": 1440, "height": 1000},
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox",
    "--lang=en-US,en",
]
MAX_SCROLLS = 12

# Counts are extracted only from compact review-related labels in the Maps UI.
# Exclude reviews/ratings cards and rating filter options from the denominator.
COUNT_PATTERNS = (
    r"(?i)(\d[\d,.\s]*)\s*(?:reviews?|recensies|beoordelingen|ulasan|리뷰|則評論|条评价|評論|ความคิดเห็น|đánh giá)\b",
    r"(?i)(?:reviews?|recensies|beoordelingen|ulasan|리뷰|評論|ความคิดเห็น|đánh giá)\s*[:(]?\s*(\d[\d,.\s]*)",
)
REVIEW_LABEL_RE = re.compile(
    r"reviews?|recensies|beoordelingen|ulasan|리뷰|評論|ความคิดเห็น|đánh giá",
    re.I,
)


def store_urls():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const\s+STORE_URL_MAP\s*=\s*(\{.*?\})\s*;", html, re.S)
    if m is None:
        raise RuntimeError("Repository STORE_URL_MAP not found")
    source = json.loads(m.group(1))
    keys = ("Bornga Dunhua South", "Saemaeul Seoul St.")
    for key in keys:
        if not source.get(key, "").startswith("https://"):
            raise RuntimeError("Invalid stored Google Maps URL: " + key)
    return [
        ("Saemaeul Central Eastville", "Thailand", CENTRAL_EASTVILLE_URL),
        ("Bornga Dunhua South", "Taiwan", source[keys[0]]),
        ("Saemaeul Seoul St.", "Mongolia", source[keys[1]]),
    ]


def raw_snapshot(page):
    # All review identifiers and text remain transient. They never enter the report.
    return page.evaluate("""() => {
        const cards = [...document.querySelectorAll('.jftiEf')];
        const tab = [...document.querySelectorAll('[role="tab"]')].find(e =>
            /reviews|리뷰|recensies|beoordelingen|ulasan/i.test(
                (e.getAttribute('aria-label') || '') + ' ' + (e.textContent || '')));
        const candidates = [];
        const entries = [...document.querySelectorAll(
            'button, [role="tab"], [role="button"], h1, h2, span, a[aria-label]'
        )];
        const rx = /reviews?|recensies|beoordelingen|ulasan|리뷰|評論|ความคิดเห็น|đánh giá/i;
        for (const el of entries) {
            if (el.closest('.jftiEf, [data-review-id], [role="radio"], [role="option"]')) continue;
            const box = el.getBoundingClientRect();
            if (box.width <= 0 || box.height <= 0) continue;
            const attr = (el.getAttribute('aria-label') || '').trim();
            const label = (el.innerText || '').trim().slice(0, 100);
            const tag = el.tagName.toLowerCase();
            if (attr.length < 100 && rx.test(attr)) candidates.push({kind:'aria', tag, label:attr});
            if (label.length < 100 && rx.test(label)) candidates.push({kind:'text', tag, label});
        }
        const h1 = [...document.querySelectorAll('h1')]
            .some(e => e.getBoundingClientRect().height > 0);
        const pathname = location.pathname;
        return {
            page_kind: pathname.includes('/maps/place/') ? 'place' :
                pathname.includes('/maps') ? 'other_maps' : 'non_maps',
            has_visible_place_heading: h1,
            review_tab_present: !!tab,
            review_tab_selected: !!tab && tab.getAttribute('aria-selected') === 'true',
            visible_cards: cards.length,
            review_feeds: [...document.querySelectorAll('[role="feed"]')]
                .filter(f => f.querySelector('.jftiEf')).length,
            count_candidates: candidates.slice(0, 130),
            ephemeral_keys: cards.map(c => c.getAttribute('data-review-id') ||
                (c.innerText || '').slice(0, 1600)).filter(Boolean)
        };
    }""")


def parse_count_candidates(items):
    """Return verified UI candidates, and a conservative consistency verdict."""
    found = []
    for item in items:
        value = item["label"].replace("\u00a0", " ")
        # Ignore rating filters such as '5 stars', and tiny counts.
        if "star" in value.lower() and not re.search(r"\d[\d,]*\s+reviews?", value, re.I):
            continue
        for pattern in COUNT_PATTERNS:
            for match in re.finditer(pattern, value):
                digits = re.sub(r"\D", "", match.group(1))
                if not digits or len(digits) > 8:
                    continue
                number = int(digits)
                if number <= 5 or number > 5_000_000:
                    continue
                found.append({"count": number, "source": item["kind"], "tag": item["tag"]})
    # Only report distinct count values, not snippets of UI or review text.
    values = sorted({item["count"] for item in found})
    if not values:
        return {"status": "UNKNOWN", "displayed_total": None, "candidates": []}
    # If values conflict, the UI doesn't yet provide an unambiguous total.
    if len(values) > 1:
        return {"status": "AMBIGUOUS", "displayed_total": None, "candidates": values}
    return {"status": "UI_DISPLAYED", "displayed_total": values[0], "candidates": values}


def snapshot(page, unique):
    raw = raw_snapshot(page)
    transient = raw.pop("ephemeral_keys")
    labels = raw.pop("count_candidates")
    for key in transient:
        unique.add(hashlib.sha256(key.encode("utf-8")).hexdigest())
    raw["unique_review_cards_seen"] = len(unique)
    raw["displayed_review_count"] = parse_count_candidates(labels)
    return raw


def scroll_target(page):
    if page.locator(".jftiEf").count() == 0:
        return None
    handle = page.locator(".jftiEf").first.evaluate_handle("""card => {
        for (let e = card.parentElement; e; e = e.parentElement) {
            const css = getComputedStyle(e);
            const r = e.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 &&
                ['auto', 'scroll'].includes(css.overflowY) &&
                e.scrollHeight > e.clientHeight + 30) return e;
        }
        return null;
    }""")
    return handle.as_element()


def run_store(browser, name, country, url):
    context = browser.new_context(**CONTEXT)
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    page = context.new_page()
    page.set_default_timeout(9000)
    known = set()
    result = {
        "store": name, "country": country, "database_writes": False,
        "entry_method": "repository_google_maps_url", "status": "STARTED",
        "snapshots": [], "scroll_rounds": 0, "xhr_fetch_during_scroll": 0,
        "scroll_movement_rounds": 0,
    }
    watch_network = False

    def response_handler(response):
        if not watch_network:
            return
        try:
            if ("google.com" in response.url or "googleapis.com" in response.url) and (
                response.request.resource_type in ("fetch", "xhr")
            ):
                result["xhr_fetch_during_scroll"] += 1
        except Exception:
            pass

    page.on("response", response_handler)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6500)
        state = snapshot(page, known)
        result["snapshots"].append({"phase": "initial", **state})

        # A short URL can resolve to an unmapped page; this is not 0 reviews.
        if state["page_kind"] != "place" or not state["has_visible_place_heading"]:
            result["status"] = "PLACE_NOT_VERIFIED"
            return result

        if state["review_tab_present"] and not state["review_tab_selected"]:
            try:
                tab = page.get_by_role("tab", name=re.compile(
                    r"reviews?|리뷰|recensies|beoordelingen|ulasan", re.I)).first
                tab.click(timeout=5000)
                page.wait_for_timeout(2500)
                state = snapshot(page, known)
                result["snapshots"].append({"phase": "after_tab_click", **state})
            except Exception as exc:
                result["tab_click_error_type"] = type(exc).__name__

        if page.locator(".jftiEf").count() == 0:
            result["status"] = "REVIEW_CARDS_UNAVAILABLE"
            return result

        pane = scroll_target(page)
        if pane is None:
            result["status"] = "SCROLL_TARGET_UNAVAILABLE"
            return result

        pane.evaluate("(el) => {el.scrollTop = 0}")
        page.wait_for_timeout(550)
        result["snapshots"].append({"phase": "scroll_start", **snapshot(page, known)})
        watch_network = True
        no_growth = 0
        for round_no in range(MAX_SCROLLS):
            before_top = pane.evaluate("(el) => el.scrollTop")
            box = pane.bounding_box()
            if not box or box["width"] <= 0 or box["height"] <= 0:
                result["status"] = "SCROLL_PANE_NOT_VISIBLE"
                break
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.wheel(0, 650)
            page.wait_for_timeout(1250)
            after_top = pane.evaluate("(el) => el.scrollTop")
            if after_top > before_top:
                result["scroll_movement_rounds"] += 1
            previous_unique = len(known)
            state = snapshot(page, known)
            result["snapshots"].append({
                "phase": "scroll_" + str(round_no + 1), **state
            })
            result["scroll_rounds"] += 1
            if len(known) > previous_unique:
                no_growth = 0
            else:
                no_growth += 1
            if len(known) >= 6:
                result["status"] = "SIX_PLUS_OBSERVED"
                break
            reached_bottom = pane.evaluate(
                "(el) => el.scrollTop >= el.scrollHeight - el.clientHeight - 3"
            )
            if reached_bottom and no_growth >= 3:
                break

        if result["status"] == "STARTED":
            result["status"] = "BELOW_SIX_OBSERVED"
    except Exception as exc:
        result["status"] = "EXECUTION_ERROR"
        result["error_type"] = type(exc).__name__
    finally:
        result["unique_review_cards_seen"] = len(known)
        counts = [
            item["displayed_review_count"]["displayed_total"]
            for item in result["snapshots"]
            if item.get("displayed_review_count", {}).get("status") == "UI_DISPLAYED"
        ]
        count_values = sorted(set(counts))
        if len(count_values) == 1:
            result["ui_review_total"] = {
                "status": "UI_DISPLAYED", "count": count_values[0]
            }
        elif len(count_values) > 1:
            result["ui_review_total"] = {
                "status": "AMBIGUOUS", "counts": count_values
            }
        else:
            result["ui_review_total"] = {"status": "UNKNOWN", "count": None}
        result["six_plus_verified"] = result["status"] == "SIX_PLUS_OBSERVED"
        page.remove_listener("response", response_handler)
        context.close()
    return result


def main():
    if os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("This read-only test refuses Supabase credentials")
    targets = store_urls()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            stores = [run_store(browser, *item) for item in targets]
        finally:
            browser.close()
    overall = {
        "store_count": len(stores), "database_writes": False,
        "any_six_plus": any(r["six_plus_verified"] for r in stores),
        "all_six_plus": all(r["six_plus_verified"] for r in stores),
        "stores": stores,
    }
    REPORT.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [
        {
            "store": r["store"], "country": r["country"],
            "ui_total": r["ui_review_total"], "observed_unique": r["unique_review_cards_seen"],
            "status": r["status"], "six_plus": r["six_plus_verified"],
            "rounds": r["scroll_rounds"], "xhr_fetch": r["xhr_fetch_during_scroll"],
        } for r in stores
    ]
    print("MULTISTORE_REVIEW_VERDICT: " + json.dumps({
        "any_six_plus": overall["any_six_plus"],
        "all_six_plus": overall["all_six_plus"], "stores": compact
    }, ensure_ascii=False))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                "## Review total vs distinct loaded reviews (read-only)\n\n"
                "| Store | Country | Maps UI review count | Unique observed | 6+ | Status |\n"
                "|---|---|---:|---:|---|---|\n"
            )
            for r in stores:
                ui = r["ui_review_total"]
                n = str(ui["count"]) if ui["status"] == "UI_DISPLAYED" else ui["status"]
                f.write(
                    f"| {r['store']} | {r['country']} | {n} | "
                    f"{r['unique_review_cards_seen']} | "
                    f"{'PASS' if r['six_plus_verified'] else 'FAIL / UNVERIFIED'} | "
                    f"{r['status']} |\n"
                )
            f.write(
                "\n6+ means distinct cards observed, not necessarily new reviews "
                "since the last crawl. No completeness or DB-storage claim.\n"
            )


if __name__ == "__main__":
    main()
