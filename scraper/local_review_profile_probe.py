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
import time
from datetime import date, timedelta
from urllib.parse import urlsplit

STORE = "Saemaeul Central Eastville"
PLACE_URL = (
    "https://www.google.com/maps/place/Saemaeul+(새마을식당)+-+Central+Eastville/"
    "@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:"
    "0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!"
    "16s%2Fg%2F11s674rmb9?entry=ttu"
)
PLACE_TOKEN = "0x484a32408c147d14"
STORE_CONFIG = {
    "thailand": {"name": STORE, "url": PLACE_URL,
                 "tokens": (PLACE_TOKEN, "/g/11s674rmb9")},
    "taiwan": {"name": "Bornga Dunhua South",
               "url": "https://www.google.com/maps/place/%E6%9C%AC%E5%AE%B6BORNGA%E9%9F%93%E5%BC%8F%E7%87%92%E8%82%89+%E6%95%A6%E5%8D%97%E5%BA%97/@25.044463,121.5499789,17z/data=!3m1!5s0x3442abdb36c3dd57:0x31070c64b44f2f5c!4m8!3m7!1s0x3442ab0779763169:0x584a72379db46e23!8m2!3d25.044463!4d121.5499789!9m1!1b1!16s%2Fg%2F11s9g6zd8p?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D",
               "tokens": ("0x584a72379db46e23", "/g/11s9g6zd8p")},
}
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


def same_place(url, store_key="thailand"):
    p = urlsplit(url)
    from urllib.parse import unquote
    path = unquote(p.path).lower()
    return (p.scheme == "https" and p.hostname in ("www.google.com", "google.com", "maps.google.com")
            and path.startswith("/maps/place/")
            and any(token in path for token in STORE_CONFIG[store_key]["tokens"]))


def displayed_total(page):
    """Read only the place-rating summary in Overview, never filter counts."""
    values = page.evaluate(r"""() => {
        const found = new Set();
        const root = document.querySelector('.F7nice');
        if (!root || root.closest('[data-review-id],.jftiEf')) return [];
        for (const el of root.querySelectorAll('span,button,[role="button"]')) {
            if (!el.getClientRects().length) continue;
            for (const value of [el.getAttribute('aria-label') || '', el.innerText || '']) {
                const v = value.trim();
                const m = v.match(/^\(?([\d,]+)\)?\s*(?:reviews?|리뷰|개 리뷰|개의 리뷰|건의 리뷰)$/i)
                    || v.match(/^(?:reviews?|리뷰)\s*[:：]?\s*\(?([\d,]+)\)?$/i)
                    || v.match(/^\(([\d,]+)\)$/);
                if (m) {
                    const n = Number(m[1].replace(/,/g, ''));
                    if (Number.isSafeInteger(n) && n >= 0) found.add(n);
                }
            }
        }
        return [...found].sort((a,b) => a-b);
    }""")
    return {"status": "UI_DISPLAYED" if len(values) == 1 else
            ("AMBIGUOUS" if values else "UNKNOWN"),
            "displayed_total": values[0] if len(values) == 1 else None,
            "candidate_counts": values}


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


def observe(page, seen, id_cache):
    """Count unique IDs in memory; track whether old cards remain in the DOM.

    Keep only aggregate output. The transient cache avoids hashing every old
    review again on each scroll and is discarded with this single run.
    """
    ids = page.locator(".jftiEf[data-review-id]").evaluate_all(
        "(cards) => cards.map(c => c.getAttribute('data-review-id')).filter(Boolean)"
    )
    current = set()
    for item in ids:
        digest = id_cache.get(item)
        if digest is None:
            digest = hashlib.sha256(item.encode("utf-8")).digest()
            id_cache[item] = digest
        current.add(digest)
    retained = seen.issubset(current)
    seen.update(current)
    return len(seen), retained


def wheel_step(mode, append_only, viewport_height):
    """Opt-in benchmark: use a larger ordinary wheel step only if cards persist.

    Baseline behavior is unchanged. If the page starts recycling cards,
    adaptive mode permanently falls back to the known 900px wheel step.
    """
    if mode != "adaptive" or not append_only:
        return 900
    return min(1800, max(900, int(viewport_height * 2)))



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


def field_audit_status(metrics, observed_unique):
    """A DOM field audit is not proof that review values are correct or complete."""
    if metrics["unique_cards"] != observed_unique:
        return "PARTIAL_DOM_FIELD_AUDIT"
    if (metrics["rating_valid"] != observed_unique
            or metrics["author_present"] != observed_unique
            or metrics["date_present"] != observed_unique):
        return "REQUIRED_FIELD_GAPS"
    return "REQUIRED_FIELDS_PRESENT"


def audit_loaded_fields(page, observed_unique, *, include_records=False):
    """Inspect loaded review cards in one DOM pass; return aggregate counts only.

    Never export individual authors, text, dates or review IDs. A blank body
    can be a rating-only review; an unexpanded body is not a full-text review.
    Do not replace missing dates/ratings with guessed values.
    """
    result = page.locator(".jftiEf[data-review-id]").evaluate_all(r"""(cards, includeRecords) => {
        const out = {
            unique_cards: 0, duplicate_cards: 0, author_present: 0,
            rating_valid: 0, date_present: 0, relative_date_label: 0,
            ambiguous_date: 0, ambiguous_rating: 0, rating_label_candidates: 0,
            unmatched_rating_labels: 0,
            body_present: 0, body_not_detected: 0, possible_collapsed_body: 0,
            rating_distribution: {"1":0,"2":0,"3":0,"4":0,"5":0}
        };
        const seen = new Set();
        const records = [];
        const txt = el => (el?.innerText || el?.textContent || '').trim();
        for (const card of cards) {
            const id = card.getAttribute('data-review-id');
            if (!id) continue;
            if (seen.has(id)) { out.duplicate_cards++; continue; }
            seen.add(id);
            out.unique_cards++;
            if (txt(card.querySelector('.d4r55'))) out.author_present++;
            // Only inspect compact metadata outside body, author, owner
            // response and action controls. Never report the raw strings.
            const isMetadata = el => !el.closest(
                '.wiI7pd,.MyEned,.d4r55,.CDe7pd,.RfnDt,button,a,[role="button"]'
            );
            const relative = /^(?:(?:수정됨|edited)\s*[:·-]?\s*)?(?:(?:\d+|한|하루|어제)\s*(?:초|분|시간|일|주|개월|달|년)?\s*전|어제|방금|(?:\d+|a|an|one)\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago)(?:\s*[·(]?\s*(?:수정됨|edited)\)?)?$/i;
            const absolute = /^(?:\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?|\d{4}년\s*\d{1,2}월\s*\d{1,2}일)$/;
            const dates = new Set();
            for (const el of card.querySelectorAll('.rsqaof,.xRkPPb,span,time')) {
                if (!isMetadata(el) || el.children.length) continue;
                const value = txt(el);
                if (relative.test(value) || absolute.test(value)) dates.add(value);
            }
            if (dates.size === 1) {
                out.date_present++;
                if (relative.test([...dates][0])) out.relative_date_label++;
            }
            if (dates.size > 1) out.ambiguous_date++;
            const ratings = new Set();
            for (const el of card.querySelectorAll('[aria-label]')) {
                if (!isMetadata(el)) continue;
                const label = (el.getAttribute('aria-label') || '').trim();
                const m = label.match(/^(?:별(?:표)?\s*([1-5])\s*개|([1-5])\s*stars?|([1-5])\s*개의?\s*별(?:표)?|평점\s*([1-5])(?:점|\s*\/\s*5)?|별점\s*([1-5])(?:점|\s*\/\s*5)?|([1-5])\s*\/\s*5\s*(?:stars?|점)?|5점\s*만점에\s*([1-5])점?)$/i);
                if (m) ratings.add(Number(m.slice(1).find(Boolean)));
                // Report only coarse label patterns and element kinds,
                // never accessible names that could identify a reviewer.
                if (/(?:별|stars?|평점)/i.test(label) && label.length <= 50) {
                    out.rating_label_candidates++;
                    if (!m) out.unmatched_rating_labels++;
                }
            }
            if (ratings.size > 1) out.ambiguous_rating++;
            if (ratings.size === 1) {
                const rating = [...ratings][0];
                out.rating_valid++;
                out.rating_distribution[String(rating)]++;
            }
            const body = [...card.querySelectorAll('.wiI7pd,.MyEned')].some(el => !!txt(el));
            if (includeRecords) {
                const primary = [...card.querySelectorAll('.wiI7pd')].find(el => el.getClientRects().length)
                    || [...card.querySelectorAll('.MyEned')].find(el => el.getClientRects().length);
                records.push({source_id:id, author:txt(card.querySelector('.d4r55')),
                    rating:ratings.size === 1 ? [...ratings][0] : null,
                    date_label:dates.size === 1 ? [...dates][0] : null,
                    body:txt(primary)});
            }
            if (body) out.body_present++;
            else out.body_not_detected++;
            if ([...card.querySelectorAll('button,[role="button"]')].some(el =>
                /^(?:자세히 보기|더보기|더 보기|more|read more|see more)$/i.test(txt(el)))) {
                out.possible_collapsed_body++;
            }
        }
        return {metrics:out, records};
    }""", include_records)
    metrics = result["metrics"]
    metrics["status"] = field_audit_status(metrics, observed_unique)
    metrics["full_text_verified"] = False
    metrics["absolute_dates_verified"] = False
    return (metrics, result["records"]) if include_records else metrics


MORE_LABEL = re.compile(r"^(?:자세히 보기|더보기|더 보기|more|read more|see more)$", re.I)
ORIGINAL_LABEL = re.compile(r"^(?:원문 보기|원본 보기|See original|Show original|View original)(?:\s*\([^()\r\n]{1,40}\))?$", re.I)


def body_measure(card):
    # Measure the main review only, not the owner's reply or extra fields.
    return card.evaluate(r"""card => {
        const visible = el => !!el.getClientRects().length;
        const primary = [...card.querySelectorAll('.wiI7pd')].find(visible)
            || [...card.querySelectorAll('.MyEned')].find(visible);
        return primary ? (primary.innerText || '').trim().length : 0;
    }""")


def detail_measure(card):
    """Count only known, visibly displayed review-detail labels, not content."""
    return card.evaluate(r"""card => {
        const visible = el => !!el.getClientRects().length;
        const labels = /^(?:식사 유형|방문 유형|1인당 가격|음식|서비스|분위기|meal type|price per person|food|service|atmosphere)(?:\s*[:：]\s*[1-5])?$/i;
        const owner = [...card.querySelectorAll('span,div')].find(el =>
            !el.children.length && /^(?:업체 대표 응답|소유자 답변|Response from the owner|Owner response)$/i.test((el.innerText || '').trim()));
        const found = new Set();
        for (const el of card.querySelectorAll('span,div')) {
            if (el.children.length || !visible(el) || el.closest('.CDe7pd,.wiI7pd')) continue;
            if (owner && (owner.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
            const value = (el.innerText || '').trim();
            if (labels.test(value)) found.add(value.toLowerCase());
        }
        return found.size;
    }""")


def body_control(card, pattern):
    """Identify only controls structurally associated with the main review.

    A card can also contain an owner's response with identical controls.
    Exclude controls in that response or associated with a later body.
    If the remaining association is ambiguous, do not click anything.
    """
    selector = 'button,[role="button"],a,[role="link"]'
    if pattern is ORIGINAL_LABEL:
        selector += ',span[jsaction]'
    candidates = card.locator(selector).filter(has_text=pattern).filter(visible=True)
    result = candidates.evaluate_all(r"""els => {
        const accepted = [];
        let excluded = 0, unresolved = 0;
        for (let i = 0; i < els.length; i++) {
            const el = els[i], card = el.closest('.jftiEf[data-review-id]');
            if (!card) { unresolved++; continue; }
            // Do not count an actionable wrapper and its matching child twice.
            if (els.some(other => other !== el && el.contains(other))) continue;
            const visible = node => !!node.getClientRects().length;
            const bodies = [...card.querySelectorAll('.wiI7pd')].filter(visible);
            const primary = bodies[0] || [...card.querySelectorAll('.MyEned')].find(visible);
            if (!primary) { unresolved++; continue; }
            const precedes = (a,b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
            const replyHeaders = [...card.querySelectorAll('span,div')].filter(node =>
                !node.children.length && /^(?:업체 대표 응답|소유자 답변|Response from the owner|Owner response)$/i.test((node.innerText || '').trim())
            );
            if (el.closest('.CDe7pd') ||
                replyHeaders.some(h => precedes(primary,h) && precedes(h,el)) ||
                bodies.slice(1).some(b => precedes(primary,b) && precedes(b,el))) {
                excluded++; continue;
            }
            let common = el, distance = 0;
            while (common && common !== card && !common.contains(primary)) {
                common = common.parentElement; distance++;
            }
            if (!common || common === card) { unresolved++; continue; }
            accepted.push({index:i, distance});
        }
        return {accepted, excluded, unresolved};
    }""")
    indexes = result["accepted"]
    # One structurally verified candidate only; no arbitrary first-button click.
    count = len(indexes) + result["unresolved"]
    return (candidates.nth(indexes[0]["index"]) if count == 1 and len(indexes) == 1 else None,
            count, result["excluded"])


def body_sample_status(metrics):
    if metrics["context_lost"]:
        return "BODY_SAMPLE_CONTEXT_LOST"
    if metrics["more_candidates"] == 0:
        return "BODY_SAMPLE_NO_EXPANSION_EVIDENCE"
    if (metrics["more_control_resolved"] != metrics["more_candidates"]
            or metrics["original_confirmed"] != metrics["original_candidates"]
            or metrics["body_missing_after"]
            or metrics["identity_mismatch"] or metrics.get("click_errors", 0)):
        return "BODY_SAMPLE_GAPS"
    return "BODY_SAMPLE_CONTROLS_VERIFIED"


def audit_body_sample(page, store_key, reviews, limit=10):
    """Bounded ordinary UI check on initially loaded cards, aggregate only."""
    cards = page.locator(".jftiEf[data-review-id]")
    n = min(cards.count(), limit)
    metrics = dict(sample_cards=n, more_candidates=0, more_confirmed=0,
                   more_length_increased=0, more_no_length_increase=0,
                   more_ambiguous=0, more_control_resolved=0,
                   more_details_increased=0, more_details_only=0,
                   more_closed_without_growth=0, more_remaining=0,
                   original_candidates=0,
                   original_confirmed=0, original_length_changed=0,
                   body_missing_after=0, identity_mismatch=0,
                   context_lost=False, click_errors=0,
                   excluded_nonreview_more=0, excluded_nonreview_original=0)
    for i in range(n):
        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
            metrics["context_lost"] = True
            break
        card = cards.nth(i)
        identity = card.get_attribute("data-review-id")
        before = body_measure(card)
        before_details = detail_measure(card)
        more, more_count, excluded = body_control(card, MORE_LABEL)
        metrics["excluded_nonreview_more"] += excluded
        if more_count:
            metrics["more_candidates"] += 1
            if more is None:
                metrics["more_ambiguous"] += 1
            else:
                try:
                    more.click(timeout=2500)
                    remaining = 1
                    for _ in range(5):
                        page.wait_for_timeout(400)
                        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                            metrics["context_lost"] = True
                            break
                        if card.get_attribute("data-review-id") != identity:
                            metrics["identity_mismatch"] += 1
                            break
                        _, remaining, _ = body_control(card, MORE_LABEL)
                        if remaining == 0:
                            break
                    if metrics["context_lost"] or metrics["identity_mismatch"]:
                        break
                    after = body_measure(card)
                    after_details = detail_measure(card)
                    grew = after > before
                    details_grew = after_details > before_details
                    if grew:
                        metrics["more_length_increased"] += 1
                    else:
                        metrics["more_no_length_increase"] += 1
                    if details_grew:
                        metrics["more_details_increased"] += 1
                    if remaining == 0 and after > 0:
                        metrics["more_control_resolved"] += 1
                        if grew:
                            metrics["more_confirmed"] += 1
                        elif details_grew:
                            metrics["more_details_only"] += 1
                        else:
                            metrics["more_closed_without_growth"] += 1
                    elif remaining:
                        metrics["more_remaining"] += 1
                except Exception:
                    metrics["click_errors"] += 1
        original, original_count, excluded = body_control(card, ORIGINAL_LABEL)
        metrics["excluded_nonreview_original"] += excluded
        if original_count:
            metrics["original_candidates"] += 1
            if original is not None:
                try:
                    before_original = body_measure(card)
                    original.click(timeout=2500)
                    page.wait_for_timeout(350)
                    if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                        metrics["context_lost"] = True
                        break
                    if card.get_attribute("data-review-id") != identity:
                        metrics["identity_mismatch"] += 1
                        break
                    after_original = body_measure(card)
                    if after_original != before_original:
                        metrics["original_length_changed"] += 1
                    _, remaining, _ = body_control(card, ORIGINAL_LABEL)
                    if remaining == 0 and after_original > 0:
                        metrics["original_confirmed"] += 1
                except Exception:
                    metrics["click_errors"] += 1
        if card.get_attribute("data-review-id") != identity:
            metrics["identity_mismatch"] += 1
            break
        if not body_measure(card):
            metrics["body_missing_after"] += 1
    metrics["status"] = body_sample_status(metrics)
    metrics["original_control_evidence"] = (
        "NOT_OBSERVED" if metrics["original_candidates"] == 0 else
        ("CONTROLS_RESOLVED" if metrics["original_confirmed"] == metrics["original_candidates"]
         else "UNRESOLVED")
    )
    # A resolved control is not proof of full text; unchanged-length cases
    # remain explicitly distinguished from demonstrated body growth.
    metrics["full_text_verified"] = False
    return metrics


def local_date_value(label, base, production):
    """Preserve unknowns; do not use the legacy estimated-today fallback."""
    if not isinstance(label, str) or not label.strip():
        return None, None
    value = label.strip()
    absolute = re.fullmatch(r"(\d{4})(?:[.\-/]\s*|년\s*)(\d{1,2})(?:[.\-/]\s*|월\s*)(\d{1,2})(?:[.일])?", value)
    if absolute:
        try:
            parsed = date(*map(int, absolute.groups()))
            return (parsed.isoformat(), "displayed") if parsed <= base else (None, None)
        except ValueError:
            return None, None
    normalized = re.sub(r"^(?:수정됨|edited)\s*[:·-]?\s*", "", value, flags=re.I)
    normalized = re.sub(r"\s*[·(]?\s*(?:수정됨|edited)\)?$", "", normalized, flags=re.I)
    normalized = re.sub(r"^한\s*(주|달|개월|년|시간|분|초)\s*전$", r"1\1 전", normalized)
    if normalized in ("어제", "하루 전"):
        age = 1
    elif normalized == "방금":
        age = 0
    else:
        age = production.relative_review_age_days(normalized)
    if age is None or age < 0 or age > 36500:
        return None, None
    return (base - timedelta(days=age)).isoformat(), "estimated"


def adapt_local_records(records, store_name, base, production):
    """Map transient visible records into the existing engine's candidate shape.

    Only for offline reconciliation. Store display name is diagnostic scope,
    never a substitute for an immutable DB store ID during a real rollout.
    """
    candidates, seen = [], set()
    gaps = dict(invalid_metadata=0, missing_source=0, duplicate_source=0)
    for raw in records:
        source = production.hash_google_source_review_id(store_name, raw.get("source_id"))
        if not source:
            gaps["missing_source"] += 1
            continue
        if source in seen:
            gaps["duplicate_source"] += 1
            continue
        seen.add(source)
        author = production.normalize_spaces(raw.get("author") or "")
        rating = raw.get("rating")
        review_date, date_source = local_date_value(raw.get("date_label"), base, production)
        if not author or author.casefold() in {"anonymous", "unknown"} or type(rating) is not int or not 1 <= rating <= 5 or not review_date:
            gaps["invalid_metadata"] += 1
            continue
        body = raw.get("body") or ""
        candidates.append(dict(store_name=store_name, author=author, rating=rating,
                               text=body, has_text=bool(body.strip()),
                               date=raw["date_label"], review_date=review_date,
                               review_date_source=date_source,
                               collected_at=base.isoformat(), google_source_id_hash=source))
    return candidates, gaps


def integration_sample(page, store_key, observed_unique):
    """Run the existing pure dedupe planner against synthetic historical rows.

    No actual database access; no credentials; no writes or raw review output.
    The sample uses visible text and must never authorize persistence.
    """
    import scraper as production
    metrics, records = audit_loaded_fields(page, observed_unique, include_records=True)
    candidates, gaps = adapt_local_records(
        records, STORE_CONFIG[store_key]["name"], production.now_kst().date(), production
    )
    # Synthetic replay of a candidate tests the legacy exact-match pathway.
    historical = [dict(candidates[0])] if candidates else []
    replay = production.plan_safe_review_append(historical, historical)
    plan = production.plan_safe_review_append(historical, candidates)
    unique = len(plan["unique_candidates"])
    matched = plan["already_matched"]
    ready, held = len(plan["ready"]), len(plan["held"])
    passed = (
        len(candidates) == observed_unique and observed_unique >= 6
        and metrics["status"] == "REQUIRED_FIELDS_PRESENT"
        and not any(gaps.values())
        and replay["already_matched"] == 1 and not replay["ready"] and not replay["held"]
        and matched + ready + held == unique
    )
    return {
        "status": "LOCAL_ADAPTER_SAMPLE_PASSED" if passed else "LOCAL_ADAPTER_SAMPLE_GAPS",
        "observed_unique": observed_unique, "adapted_candidates": len(candidates),
        "metadata_gaps": gaps, "legacy_unique_candidates": unique,
        "legacy_key_collapses": len(candidates) - unique,
        "synthetic_history_rows": len(historical), "synthetic_matched": matched,
        "synthetic_ready": ready, "synthetic_held": held,
        "synthetic_held_reasons": plan["held_reasons"],
        "synthetic_replay_matched": replay["already_matched"],
        "synthetic_replay_new": len(replay["ready"]),
        "actual_database_compared": False, "database_writes": False,
        "full_text_verified": False, "write_approved": False,
    }


def coverage_status(count, expected, blocked=False):
    """Compare against the user-observed count, not proof of an API snapshot."""
    if blocked:
        return "ACCESS_RESTRICTED_STOPPED"
    if count == expected:
        return "EXPECTED_COUNT_MATCHED"
    if count > expected:
        return "EXPECTED_COUNT_EXCEEDED_RECHECK_TOTAL"
    return "EXPECTED_COUNT_NOT_REACHED"


def run_once(context, expected_total=None, store_key="thailand", auto_total=False, scroll_mode="baseline", audit_fields=False, field_sample=False, body_sample=False, adapter_sample=False):
    report = {"status": "NOT_STARTED", "phase": "select_startup_tab",
              "overview_selected": False,
              "reviews_selected": False, "initial_unique": 0,
              "observed_unique": 0, "scroll_rounds": 0,
              "scroll_verified": False, "database_writes": False,
              "full_coverage_verified": False}
    report["store"] = STORE_CONFIG[store_key]["name"]
    if expected_total is not None:
        report["expected_total_user_observed"] = expected_total
        report["additional_unique"] = 0
        report["stop_reason"] = None
    report["scroll_mode"] = scroll_mode
    report["larger_wheel_rounds"] = 0
    report["append_only_retained"] = True
    started = time.monotonic()
    scroll_started = None
    page = None
    seen = set()
    id_cache = {}
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
        # Field/body diagnostics and explicit-count checks do not need
        # Overview navigation. Use the configured place link directly.
        # Preserve the verified Thailand Overview path for auto-total only.
        if store_key == "thailand" and auto_total:
            failure = find_store_by_search(page, report)
            if failure:
                report["status"] = failure
                return report
        else:
            report["phase"] = "open_configured_store"
            report["entry_method"] = "repository_store_url"
            page.goto(STORE_CONFIG[store_key]["url"], wait_until="domcontentloaded", timeout=45000)
            for _ in range(20):
                page.wait_for_timeout(1000)
                if blocked(page):
                    report["status"] = "ACCESS_RESTRICTED_STOPPED"
                    return report
                if same_place(page.url, store_key):
                    break
            if not same_place(page.url, store_key):
                report["status"] = "PLACE_NOT_VERIFIED"
                return report

        report["phase"] = "find_overview_tab"
        overview = find_visible_tab(page, OVERVIEW_TAB)
        report["phase"] = "find_reviews_tab"
        reviews = find_visible_tab(page, REVIEW_TAB)
        report["phase"] = "verify_selected_tab"
        report["overview_selected"] = selected(overview)
        report["reviews_selected_at_entry"] = selected(reviews)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        if not same_place(page.url, store_key):
            report["status"] = "PLACE_NOT_VERIFIED"
            return report

        if report["overview_selected"]:
            report["phase"] = "read_overview_total"
            report["overview_total"] = displayed_total(page)
            report["phase"] = "select_reviews"
            reviews.click(timeout=5000)
        elif report["reviews_selected_at_entry"]:
            # A canonical place link may open the review tab directly.
            # Keep that verified state instead of forcing an unnecessary
            # navigation back to Overview.
            report["overview_total"] = {"status": "NOT_OBSERVED",
                                        "displayed_total": None, "candidate_counts": []}
        else:
            report["status"] = "ENTRY_TAB_NOT_VERIFIED"
            return report

        report["phase"] = "verify_reviews"
        for _ in range(15):
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if selected(reviews) and same_place(page.url, store_key):
                break
            page.wait_for_timeout(1000)
        report["reviews_selected"] = selected(reviews)
        if not report["reviews_selected"] or not same_place(page.url, store_key):
            report["status"] = "REVIEWS_NOT_VERIFIED"
            return report

        if auto_total:
            expected_total = report["overview_total"]["displayed_total"]
            if expected_total is None or not 1 <= expected_total <= 1000:
                report["status"] = "DISPLAYED_TOTAL_NOT_VERIFIED_OR_OUT_OF_SCOPE"
                return report
            report["expected_total_user_observed"] = expected_total
            report["expected_total_source"] = "overview_rating_summary"
            report["additional_unique"] = 0
            report["stop_reason"] = None

        page.wait_for_timeout(3000)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        if not selected(reviews) or not same_place(page.url, store_key):
            report["status"] = "REVIEW_CONTEXT_LOST"
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
        report["initial_unique"], _ = observe(page, seen, id_cache)
        report["observed_unique"] = len(seen)
        if field_sample or body_sample or adapter_sample:
            report["phase"] = "initial_field_sample"
            report["field_audit"] = audit_loaded_fields(page, len(seen))
            report["status"] = (
                "FIELD_SAMPLE_VERIFIED"
                if len(seen) >= 6 and report["field_audit"]["status"] == "REQUIRED_FIELDS_PRESENT"
                else "FIELD_SAMPLE_GAPS"
            )
            if adapter_sample and report["status"] == "FIELD_SAMPLE_VERIFIED":
                report["phase"] = "local_adapter_sample"
                report["integration_sample"] = integration_sample(page, store_key, len(seen))
                report["status"] = report["integration_sample"]["status"]
            if body_sample and report["status"] == "FIELD_SAMPLE_VERIFIED":
                report["phase"] = "body_sample"
                report["body_sample"] = audit_body_sample(page, store_key, reviews)
                report["status"] = report["body_sample"]["status"]
            return report
        # Count IDs only in memory. Do not extract or save review contents.
        # The count check is bounded and never circumvents a restriction.
        idle = 0
        scroll_started = time.monotonic()
        report["phase"] = "scroll_review_pane"
        max_rounds = 240 if expected_total is not None else 8
        for i in range(1, max_rounds + 1):
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if not same_place(page.url, store_key) or not selected(reviews):
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
            step = wheel_step(
                scroll_mode, report["append_only_retained"], box["height"]
            )
            page.mouse.wheel(0, step)
            if step > 900:
                report["larger_wheel_rounds"] += 1
            # Preserve the validated wait; no increased request cadence.
            page.wait_for_timeout(1800)
            report["scroll_rounds"] = i
            report["observed_unique"], retained = observe(page, seen, id_cache)
            report["append_only_retained"] = report["append_only_retained"] and retained
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
                        "elapsed_scroll_seconds": round(time.monotonic() - scroll_started, 1),
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
        if audit_fields and report["status"] == "EXPECTED_COUNT_MATCHED":
            report["phase"] = "audit_loaded_fields"
            if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                report["status"] = "FIELD_AUDIT_CONTEXT_UNVERIFIED"
                return report
            report["field_audit"] = audit_loaded_fields(page, len(seen))
            report["phase"] = "final_field_audit"
        return report
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["status"] = (
            "BROWSER_CONNECTION_LOST"
            if report["error_type"] == "TargetClosedError" else "PROBE_ERROR"
        )
        return report
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        report["elapsed_scroll_seconds"] = (round(time.monotonic() - scroll_started, 1)
                                            if scroll_started is not None else None)
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
    assert same_place(STORE_CONFIG["taiwan"]["url"], "taiwan")
    assert not same_place(STORE_CONFIG["taiwan"]["url"], "thailand")
    assert not same_place(PLACE_URL, "taiwan")
    assert wheel_step("baseline", True, 800) == 900
    assert wheel_step("adaptive", False, 800) == 900
    assert wheel_step("adaptive", True, 700) == 1400
    assert wheel_step("adaptive", True, 1200) == 1800
    assert wheel_step("adaptive", True, 300) == 900
    # Test repeated IDs and recycled DOM cards without a browser.
    class FakeCards:
        def __init__(self):
            self.ids = ["a", "b", "a"]
        def evaluate_all(self, _):
            return self.ids
    class FakePage:
        def __init__(self):
            self.cards = FakeCards()
        def locator(self, _):
            return self.cards
    fake = FakePage()
    seen, cache = set(), {}
    assert observe(fake, seen, cache) == (2, True)
    fake.cards.ids = ["a", "b", "c"]
    assert observe(fake, seen, cache) == (3, True)
    fake.cards.ids = ["c", "d"]
    assert observe(fake, seen, cache) == (4, False)
    assert len(cache) == 4
    metrics = {"unique_cards": 167, "rating_valid": 167,
               "author_present": 167, "date_present": 167}
    assert field_audit_status(metrics, 167) == "REQUIRED_FIELDS_PRESENT"
    assert field_audit_status(metrics, 168) == "PARTIAL_DOM_FIELD_AUDIT"
    assert field_audit_status(dict(metrics, rating_valid=166), 167) == "REQUIRED_FIELD_GAPS"
    assert field_audit_status(dict(metrics, date_present=166), 167) == "REQUIRED_FIELD_GAPS"
    assert MORE_LABEL.fullmatch("더보기")
    assert not MORE_LABEL.fullmatch("More reviews")
    assert ORIGINAL_LABEL.fullmatch("원문 보기")
    assert ORIGINAL_LABEL.fullmatch("원본 보기(태국어)")
    assert ORIGINAL_LABEL.fullmatch("See original (Thai)")
    assert not ORIGINAL_LABEL.fullmatch("원본 보기(태국어) 공유")
    assert not ORIGINAL_LABEL.fullmatch("Like")
    sample = dict(context_lost=False, more_candidates=10, more_confirmed=6,
                  more_control_resolved=10, original_candidates=2, original_confirmed=2,
                  body_missing_after=0, identity_mismatch=0)
    assert body_sample_status(sample) == "BODY_SAMPLE_CONTROLS_VERIFIED"
    assert body_sample_status(dict(sample, more_control_resolved=9)) == "BODY_SAMPLE_GAPS"
    assert body_sample_status(dict(sample, context_lost=True)) == "BODY_SAMPLE_CONTEXT_LOST"
    assert body_sample_status(dict(sample, click_errors=1)) == "BODY_SAMPLE_GAPS"
    assert body_sample_status(dict(sample, original_confirmed=1)) == "BODY_SAMPLE_GAPS"
    class FakeProduction:
        @staticmethod
        def relative_review_age_days(label):
            return {"2개월 전": 60, "1달 전": 30}.get(label)
    base = date(2026, 11, 24)
    assert local_date_value("2026.11.20", base, FakeProduction) == ("2026-11-20", "displayed")
    assert local_date_value("2026.02.30", base, FakeProduction) == (None, None)
    assert local_date_value("2027.01.01", base, FakeProduction) == (None, None)
    assert local_date_value("2개월 전", base, FakeProduction) == ("2026-09-25", "estimated")
    assert local_date_value("수정됨: 어제", base, FakeProduction) == ("2026-11-23", "estimated")
    assert local_date_value("한 달 전", base, FakeProduction) == ("2026-10-25", "estimated")
    assert local_date_value("unknown", base, FakeProduction) == (None, None)
    print("SELF_TEST_PASS: 54 checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--inspect-on-failure", action="store_true",
                        help="Keep the visible Chrome window open after a failed check until Enter.")
    parser.add_argument("--expected-total", type=int,
                        help="Single read-only count comparison against the number seen in Maps.")
    parser.add_argument("--store", choices=sorted(STORE_CONFIG), default="thailand")
    parser.add_argument("--auto-total", action="store_true",
                        help="Read total from verified Overview rating summary.")
    parser.add_argument("--runs", type=int, choices=(1, 3), default=3,
                        help="Independent Chrome starts for the small depth diagnostic.")
    parser.add_argument("--scroll-mode", choices=("baseline", "adaptive"), default="baseline",
                        help="Opt-in ordinary wheel-step benchmark; baseline remains the default.")
    parser.add_argument("--audit-fields", action="store_true",
                        help="Inspect field presence on the count-matched DOM; aggregate only.")
    parser.add_argument("--field-sample", action="store_true",
                        help="Audit initially loaded cards only; no scrolling or full-store rescan.")
    parser.add_argument("--body-sample", action="store_true",
                        help="Check More and Original controls on up to ten initial cards; aggregate only.")
    parser.add_argument("--adapter-sample", action="store_true",
                        help="Read-only sample mapping and synthetic legacy replay; no database access.")
    args = parser.parse_args()
    if args.adapter_sample and (args.body_sample or args.field_sample or args.audit_fields or args.auto_total or args.expected_total is not None):
        parser.error("--adapter-sample is a standalone diagnostic")
    if args.body_sample and (args.field_sample or args.audit_fields or args.auto_total or args.expected_total is not None):
        parser.error("--body-sample is a standalone diagnostic")
    if args.field_sample and (args.audit_fields or args.auto_total or args.expected_total is not None):
        parser.error("--field-sample is a standalone diagnostic")
    if args.audit_fields and not (args.auto_total or args.expected_total is not None):
        parser.error("--audit-fields requires --auto-total or --expected-total")
    if args.auto_total and args.expected_total is not None:
        parser.error("choose --auto-total or --expected-total, not both")
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
    count_mode = args.auto_total or args.expected_total is not None
    target_runs = 1 if count_mode or args.field_sample or args.body_sample or args.adapter_sample else args.runs
    success_status = "FIELD_SAMPLE_VERIFIED" if args.field_sample else ("EXPECTED_COUNT_MATCHED" if count_mode else "REVIEW_DEPTH_VERIFIED")
    if args.body_sample:
        success_status = "BODY_SAMPLE_CONTROLS_VERIFIED"
    if args.adapter_sample:
        success_status = "LOCAL_ADAPTER_SAMPLE_PASSED"
    for attempt in range(1, target_runs + 1):
        context = None
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                )
                try:
                    report = run_once(context, args.expected_total, args.store, args.auto_total, args.scroll_mode, args.audit_fields, args.field_sample, args.body_sample, args.adapter_sample)
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
    final_status = (
        ("LOCAL_EXPECTED_COUNT_MATCHED" if passed else "LOCAL_COUNT_UNVERIFIED")
        if count_mode else
        (("THREE_LOCAL_DEPTH_CHECKS_PASSED" if target_runs == 3 else "LOCAL_DEPTH_CHECK_PASSED")
         if passed else "LOCAL_DEPTH_NOT_STABLE")
    )
    if args.field_sample:
        final_status = "LOCAL_FIELD_SAMPLE_PASSED" if passed else "LOCAL_FIELD_SAMPLE_GAPS"
    if args.body_sample:
        final_status = "LOCAL_BODY_SAMPLE_PASSED" if passed else "LOCAL_BODY_SAMPLE_GAPS"
    if args.adapter_sample:
        final_status = "LOCAL_ADAPTER_SAMPLE_PASSED" if passed else "LOCAL_ADAPTER_SAMPLE_GAPS"
    print("LOCAL_REVIEW_FINAL: " + json.dumps({
        "status": final_status,
        "attempts": len(reports), "database_writes": False,
        "store": STORE_CONFIG[args.store]["name"],
        "expected_total_user_observed": reports[-1].get("expected_total_user_observed") if reports else args.expected_total,
        "observed_unique": reports[-1].get("observed_unique", 0) if reports else 0,
        "scroll_mode": args.scroll_mode,
        "scroll_rounds": reports[-1].get("scroll_rounds", 0) if reports else 0,
        "elapsed_scroll_seconds": reports[-1].get("elapsed_scroll_seconds") if reports else None,
        "field_audit": reports[-1].get("field_audit") if reports else None,
        "body_sample": reports[-1].get("body_sample") if reports else None,
        "integration_sample": reports[-1].get("integration_sample") if reports else None,
        "full_coverage_verified": False,
    }), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
