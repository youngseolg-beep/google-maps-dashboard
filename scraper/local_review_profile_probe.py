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
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

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
    """Require the same complete canonical place ID, not a matching substring."""
    expected = exact_place_pair(STORE_CONFIG[store_key]["url"])
    return expected is not None and exact_place_pair(url) == expected


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


def displayed_reviews_total(page):
    """Read the place rating summary before Sort in the selected Reviews panel.

    Only explicit review-count labels and a separate rating value qualify.
    Never use author counts, keyword chips, cards, or arbitrary page numbers.
    """
    evidence = page.evaluate(r"""() => {
        const visible = e => {
            const r=e.getBoundingClientRect(), s=getComputedStyle(e);
            return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
        };
        const sortLabel = /^(?:sort(?: reviews)?|정렬)$/i;
        const sorts = [...document.querySelectorAll('button,[role="button"]')]
            .filter(e => visible(e) && !e.closest('[data-review-id],.jftiEf') &&
                [e.innerText||'',e.getAttribute('aria-label')||''].some(v=>sortLabel.test(v.trim())));
        if (sorts.length!==1) return {candidate_counts:[], reason:'SORT_ANCHOR_UNVERIFIED'};
        const sort=sorts[0];
        const countLabel=/^((?:\d{1,3}(?:,\d{3})+|\d+))\s+reviews?$/i;
        const ratingLabel=/^(?:[1-4](?:\.\d)?|5(?:\.0)?)$/;
        for(let root=sort.parentElement;root && root!==document.body;root=root.parentElement){
            const found=new Set();
            let rating=false;
            for(const e of root.querySelectorAll('span,div,button,[role="button"]')){
                if(e===sort || e.contains(sort) || !visible(e) ||
                    e.closest('[data-review-id],.jftiEf') ||
                    !(sort.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_PRECEDING)) continue;
                for(const value of [e.innerText||'',e.getAttribute('aria-label')||'']){
                    const v=value.trim();
                    const m=v.match(countLabel);
                    if(m){
                        const n=Number(m[1].replace(/,/g,''));
                        if(Number.isSafeInteger(n)) found.add(n);
                    }
                    if(ratingLabel.test(v) && v.includes('.')) rating=true;
                }
            }
            if(found.size && rating) return {candidate_counts:[...found].sort((a,b)=>a-b),reason:'RATING_SUMMARY_BEFORE_SORT'};
        }
        return {candidate_counts:[],reason:'RATING_SUMMARY_UNVERIFIED'};
    }""")
    values = evidence["candidate_counts"]
    return {"status":"UI_DISPLAYED" if len(values)==1 else ("AMBIGUOUS" if values else "UNKNOWN"),
            "displayed_total":values[0] if len(values)==1 else None,
            "candidate_counts":values, "reason":evidence["reason"]}


def stable_overview_total(first, second):
    """Accept only equal, unambiguous, bounded totals from two observations."""
    for sample in (first, second):
        if not isinstance(sample, dict) or sample.get("status") != "UI_DISPLAYED":
            return None
        n = sample.get("displayed_total")
        if type(n) is not int or not 1 <= n <= MAX_EXPECTED_COUNT or sample.get("candidate_counts") != [n]:
            return None
    return first["displayed_total"] if first["displayed_total"] == second["displayed_total"] else None


def result_status(count, blocked=False, scroll_verified=False):
    if blocked:
        return "ACCESS_RESTRICTED_STOPPED"
    if count >= 6 and scroll_verified:
        return "REVIEW_DEPTH_VERIFIED"
    return "REVIEW_DEPTH_UNVERIFIED"


def fresh_depth_status(initial, observed, restricted=False):
    """Require new unique review IDs, not just movement within initial cards."""
    return result_status(observed, restricted, observed > initial)


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


def initial_card_poll(read, wait, seconds=45, reveal=None):
    """Wait for exact cards; optionally scroll a verified review summary pane.

    The callback uses ordinary mouse wheel input and never clicks Sort/filter.
    At most six reveal attempts, spaced by at least three one-second waits.
    """
    if type(seconds) is not int or not 1 <= seconds <= 45:
        raise ValueError("INITIAL_CARD_WAIT_OUT_OF_SCOPE")
    attempts = 0
    for tick in range(seconds + 1):
        status, evidence = read()
        if status:
            return status, tick, evidence
        if evidence["visible_expected_cards"] > 0:
            return "INITIAL_REVIEW_CARDS_VISIBLE", tick, evidence
        if reveal is not None and 4 <= tick < seconds and (tick - 4) % 3 == 0 and attempts < 6:
            reveal()
            attempts += 1
        if tick < seconds:
            wait()
    return "INITIAL_REVIEW_CARDS_TIMEOUT", seconds, evidence


def review_summary_pane(page):
    """Identify the scrollable ancestor of the unique visible Sort control.

    Do not select a generic feed, map canvas, filter chip or document body.
    This is only a bootstrap for the card-anchored scroll path.
    """
    controls = page.get_by_role("button", name=re.compile(r"^(?:sort(?: reviews)?|정렬)$", re.I)).filter(visible=True)
    if controls.count() != 1:
        return None
    handle = controls.first.evaluate_handle("""button => {
        for (let el=button.parentElement; el && el!==document.body; el=el.parentElement) {
            const r=el.getBoundingClientRect(), css=getComputedStyle(el);
            if (r.width>=160 && r.height>=150 &&
                ['auto','scroll'].includes(css.overflowY) &&
                el.scrollHeight>el.clientHeight+30) return el;
        }
        return null;
    }""")
    element = handle.as_element()
    if element is None:
        handle.dispose()
    return element


def reveal_initial_cards(page, store_key, reviews):
    if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
        return "CONTEXT_UNVERIFIED"
    pane = review_summary_pane(page)
    if pane is None:
        return "SUMMARY_PANE_UNVERIFIED"
    try:
        point = pane.evaluate("""el => {
            const r=el.getBoundingClientRect();
            const l=Math.max(0,r.left), t=Math.max(0,r.top),
                  right=Math.min(innerWidth,r.right), bottom=Math.min(innerHeight,r.bottom);
            if(right-l<40 || bottom-t<40) return null;
            const x=(l+right)/2, y=(t+bottom)/2;
            if(!el.contains(document.elementFromPoint(x,y))) return null;
            return {x,y,at_end: el.scrollTop+el.clientHeight>=el.scrollHeight-2};
        }""")
        if not point:
            return "SUMMARY_PANE_POINT_UNVERIFIED"
        if point["at_end"]:
            return "SUMMARY_PANE_AT_END"
        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
            return "CONTEXT_UNVERIFIED"
        page.mouse.move(point["x"],point["y"])
        page.mouse.wheel(0,600)
        return "SUMMARY_PANE_WHEEL"
    finally:
        pane.dispose()


def initial_card_evidence(page):
    """Only structural counts; no text, account data, or review IDs."""
    return page.evaluate("""() => {
        const visible = e => {
            const r = e.getBoundingClientRect();
            const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const count = sel => [...document.querySelectorAll(sel)].filter(visible).length;
        return {
            visible_expected_cards: count('.jftiEf[data-review-id]'),
            visible_review_id_nodes: count('[data-review-id]'),
            visible_review_class_nodes: count('.jftiEf'),
            visible_feeds: count('[role="feed"]'),
            visible_busy_nodes: count('[aria-busy="true"],[role="progressbar"]')
        };
    }""")


def newest_menu_item(page):
    """Require one exact visible semantic sort option, not arbitrary text."""
    options = page.locator('[role="menuitemradio"],[role="radio"],[role="option"],[role="menuitem"]')
    options = options.filter(visible=True).filter(has_text=re.compile(r"^Newest$", re.I))
    return options.first if options.count() == 1 else None


def newest_option_selected(option):
    return option is not None and (
        option.get_attribute("aria-checked") == "true"
        or option.get_attribute("aria-selected") == "true")


def sort_menu_evidence(page):
    """Bounded structural evidence from exact known sort options only.

    No review text, profile data, URLs, arbitrary labels or HTML in output.
    Class/indicator evidence is diagnostic only, not selection proof.
    """
    return page.evaluate(r"""() => {
        const names = /^(most relevant|newest|highest rating|lowest rating)$/i;
        const visible=e=>{
            const r=e.getBoundingClientRect(),s=getComputedStyle(e);
            return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
        };
        const state=e=>Object.fromEntries(['aria-checked','aria-selected','aria-pressed','aria-current']
            .map(k=>{const v=e.getAttribute(k); return [k, v===null?null: v==='true'||v==='false'?v:'other'];}));
        const classes=e=>[...e.classList].filter(x=>/^[a-zA-Z0-9_-]{1,40}$/.test(x)).slice(0,12);
        const opts=[...document.querySelectorAll('[role="menuitemradio"],[role="radio"],[role="option"],[role="menuitem"]')]
            .filter(e=>visible(e)&&names.test((e.innerText||'').trim()));
        return opts.slice(0,8).map(e=>({
            label:(e.innerText||'').trim().toLowerCase(),
            role:e.getAttribute('role'), state:state(e), classes:classes(e),
            native_checked:[...e.querySelectorAll('input[type="radio"],input[type="checkbox"]')].slice(0,4).map(x=>x.checked),
            indicators:[...e.querySelectorAll('span,i,svg,[aria-checked],[aria-selected],[aria-pressed]')]
                .filter(visible).slice(0,16).map(x=>({
                    tag:x.tagName.toLowerCase(),classes:classes(x),state:state(x),
                    check_label:/^(check|checked|selected|checkmark)$/i.test((x.getAttribute('aria-label')||x.textContent||'').trim())
                }))
        }));
    }""")


def all_sort_options_unmarked(options):
    expected = {"most relevant","newest","highest rating","lowest rating"}
    return (len(options)==4 and {x["label"] for x in options}==expected
            and all(x["role"]=="menuitemradio" and x["state"]["aria-checked"]=="false"
                    and all(x["state"][k] in (None,"false") for k in ("aria-selected","aria-pressed","aria-current"))
                    and not any(x["native_checked"])
                    and not any(i["check_label"] or any(v=="true" for v in i["state"].values()) for i in x["indicators"])
                    for x in options))


def relative_age_interval(label):
    """Coarse displayed-age bands, not absolute dates or publication times."""
    if not isinstance(label,str):
        return None
    value = re.sub(r"^(?:edited|updated)\s*[:·-]?\s*", "", label.strip(), flags=re.I)
    value = re.sub(r"\s*[·(]?\s*(?:edited|updated)\)?$", "", value, flags=re.I)
    m = re.fullmatch(r"(\d+|a|an|one)\s+(second|minute|hour|day|week|month|year)s?\s+ago",value,re.I)
    if not m:
        return None
    n = int(m[1]) if m[1].isdigit() and len(m[1])<=6 else (1 if m[1].lower() in {"a","an","one"} else -1)
    if not 0<=n<=100000:
        return None
    units={"second":(1,1),"minute":(60,60),"hour":(3600,3600),"day":(86400,86400),
           "week":(604800,604800),"month":(28*86400,31*86400),"year":(365*86400,366*86400)}
    lo,hi=units[m[2].lower()]
    # Broad bands allow rounding/relative-label boundary ambiguity.
    return (max(0,n-1)*lo,(n+1)*hi)


def displayed_age_evidence(labels):
    bands=[relative_age_interval(x) for x in labels]
    known=[b for b in bands if b is not None]
    inversions=sum(a[0]>b[1] for i,a in enumerate(known) for b in known[i+1:])
    informative=sum(a[1]<b[0] for i,a in enumerate(known) for b in known[i+1:])
    return {"sample_size":len(labels),"parseable":len(known),"unknown":len(labels)-len(known),
            "clear_inversions":inversions,"clear_newer_before_older_pairs":informative,
            "displayed_order_consistent":bool(labels) and len(known)==len(labels) and not inversions and informative>0,
            "absolute_dates_verified":False,"publication_order_verified":False}


# Shared metadata extractor used by the previously validated full field audit
# and the bounded newest-head diagnostic. Only one unique date label qualifies.
REVIEW_DATE_METADATA_JS = r"""card => {
    const txt = el => (el?.innerText || el?.textContent || '').trim();
const isMetadata = el => !el.closest(
    '.wiI7pd,.MyEned,.d4r55,.CDe7pd,.RfnDt,button,a,[role="button"]'
);
const edited = /(?:수정(?:됨|일)?|edited|updated)/i;
const cleanDate = value => value.replace(/\s+/g, ' ').trim()
    .replace(/^(?:수정(?:됨|일)?|edited|updated)\s*[:：·-]?\s*/i, '')
    .replace(/\s*[·(]?\s*(?:수정(?:됨|일)?|edited|updated)\)?$/i, '').trim();
const relative = /^(?:(?:\d+|한)\s*(?:초|분|시간|일|주|개월|달|년)\s*전|일주일\s*전|하루\s*전|어제|방금|(?:\d+|a|an|one)\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago)$/i;
const absolute = /^(?:\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?|\d{4}년\s*\d{1,2}월\s*\d{1,2}일)$/;
const dates = new Set();
const dedicated = [...card.querySelectorAll('.rsqaof,.xRkPPb')].filter(isMetadata);
// A dedicated date element can wrap its visible date in child spans.
// Other metadata candidates must remain leaf nodes.
const dateNodes = [...new Set([...dedicated, ...card.querySelectorAll('span,time')])];
for (const el of dateNodes) {
    if (!isMetadata(el) || !el.getClientRects().length ||
        (el.children.length && !dedicated.includes(el))) continue;
    const value = cleanDate(txt(el));
    if (relative.test(value) || absolute.test(value)) dates.add(value);
}

    return {dates, dedicated, isMetadata, edited, relative};
}"""


def ordered_date_sample(page):
    """Read exact card IDs and dates using the shared validated metadata logic."""
    records=page.locator(".jftiEf[data-review-id]").evaluate_all(r"""cards => {
        const readDates = """ + REVIEW_DATE_METADATA_JS + r""";
        return cards.map(card => {
            const {dates} = readDates(card);
            return {id:card.getAttribute('data-review-id'), label:dates.size===1?[...dates][0]:null};
        });
    }""")
    ids=[r["id"] for r in records]
    if not ids or len(ids)>300 or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
        return None, []
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in ids],[r["label"] for r in records]


def verify_newest_sort(page, store_key, reviews, evidence=None):
    """Use only ordinary visible Sort controls; require explicit selected state."""
    def context_ok():
        return not blocked(page) and same_place(page.url, store_key) and selected(reviews)
    def failure():
        return "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
    def record(stage):
        if evidence is not None:
            evidence.append({"stage":stage,"options":sort_menu_evidence(page)})
    if not context_ok():
        return failure()
    before_head, before_labels = ordered_date_sample(page)
    if evidence is not None:
        evidence.append({"stage":"before_head","date_evidence":displayed_age_evidence(before_labels)})
    sorts = page.get_by_role("button", name=re.compile(r"^(?:sort(?: reviews)?|sort by newest)$", re.I)).filter(visible=True)
    if sorts.count() != 1:
        return "NEWEST_SORT_CONTROL_UNVERIFIED"
    sorts.first.click(timeout=5000)
    page.wait_for_timeout(1000)
    if not context_ok():
        return failure()
    record("before_selection")
    before_unmarked = all_sort_options_unmarked(sort_menu_evidence(page))
    clicked_and_closed = False
    option = newest_menu_item(page)
    if option is None:
        return "NEWEST_SORT_OPTION_UNVERIFIED"
    if not newest_option_selected(option):
        option.click(timeout=5000)
        page.wait_for_timeout(2500)
        if not context_ok():
            return failure()
        record("after_selection")
        # Reopen the menu only if selection closed it.
        if newest_menu_item(page) is None:
            clicked_and_closed = True
            if sorts.count() != 1:
                return "NEWEST_SORT_CONTROL_UNVERIFIED"
            sorts.first.click(timeout=5000)
            page.wait_for_timeout(1000)
            if not context_ok():
                return failure()
    record("selection_recheck")
    explicit = newest_option_selected(newest_menu_item(page))
    diagnostic_only = (not explicit and before_unmarked and clicked_and_closed
                       and all_sort_options_unmarked(sort_menu_evidence(page)))
    if not explicit and not diagnostic_only:
        return "NEWEST_SORT_SELECTION_UNVERIFIED"
    page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    if not context_ok():
        return failure()
    if newest_menu_item(page) is not None:
        return "NEWEST_SORT_MENU_NOT_CLOSED"
    after_head, after_labels = ordered_date_sample(page)
    if evidence is not None:
        evidence.append({"stage":"after_head","head_changed":before_head!=after_head if before_head and after_head else None,
                         "date_evidence":displayed_age_evidence(after_labels)})
    return "NEWEST_SORT_UI_VERIFIED" if explicit else "NEWEST_SORT_ACTION_OBSERVED_ONLY"


def ordered_head(page):
    """Transient hashed exact-card sequence; reject duplicates and missing IDs."""
    ids = page.locator(".jftiEf[data-review-id]").evaluate_all(
        "(cards) => cards.map(c => c.getAttribute('data-review-id'))")
    if not ids or len(ids) > 300 or any(not isinstance(x,str) or not x for x in ids):
        return None
    if len(set(ids)) != len(ids):
        return None
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in ids]


def ordered_extension(before, after):
    return isinstance(before,list) and isinstance(after,list) and bool(before) and after[:len(before)] == before


def compare_newest_heads(heads, target=30):
    if len(heads) != 2 or any(len(h) != target or len(set(h)) != target for h in heads):
        return {"status":"NEWEST_HEAD_COMPARISON_INCOMPLETE","compared":0,"write_approved":False}
    match = heads[0] == heads[1]
    return {"status":"NEWEST_HEAD_MATCHED" if match else "NEWEST_HEAD_CHANGED",
            "compared":target,"position_matches":sum(a==b for a,b in zip(*heads)),
            "shared_ids":len(set(heads[0])&set(heads[1])),
            "write_approved":False,"stop_authorized":False}


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
    handle = cards.first.evaluate_handle("""card => {
        for (let el=card.parentElement; el && el!==document.body; el=el.parentElement) {
            const r=el.getBoundingClientRect(), css=getComputedStyle(el);
            if (r.width>0 && r.height>0 && ['auto','scroll'].includes(css.overflowY)
                && el.scrollHeight>el.clientHeight+30) return el;
        }
        return null;
    }""")
    element = handle.as_element()
    if element is None:
        handle.dispose()
    return element


def pane_geometry(pane):
    if pane is None:
        return None
    return pane.evaluate("""el => ({
        top: Math.round(el.scrollTop), height: Math.round(el.scrollHeight),
        viewport: Math.round(el.clientHeight),
        at_bottom: el.scrollTop + el.clientHeight >= el.scrollHeight - 3
    })""")


def stall_evidence_status(geometry, busy_count):
    if not isinstance(geometry, dict):
        return "PANE_UNVERIFIED"
    if busy_count:
        return "VISIBLE_BUSY_INDICATOR"
    return "PANE_BOTTOM_NO_VISIBLE_BUSY" if geometry.get("at_bottom") is True else "PANE_NOT_AT_BOTTOM"


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
        const mainBody = """ + MAIN_BODY_JS + r""";
        const readDates = """ + REVIEW_DATE_METADATA_JS + r""";
        const out = {
            unique_cards: 0, duplicate_cards: 0, author_present: 0,
            rating_valid: 0, date_present: 0, relative_date_label: 0,
            ambiguous_date: 0, ambiguous_rating: 0, rating_label_candidates: 0,
            date_missing_dedicated_node: 0, date_missing_nested_node: 0,
            date_missing_label_shapes: {},
            unmatched_rating_labels: 0,
            body_present: 0, body_not_detected: 0, possible_collapsed_body: 0,
            scoped_primary_body_present: 0, scoped_primary_body_blank: 0,
            scoped_body_fallback_unverified: 0, scoped_body_ambiguous: 0, scoped_body_not_detected: 0,
            unverified_body_structure: {},
            unverified_with_owner_header: 0,
            body_absence_evidence: {},
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
            const {dates, dedicated, isMetadata, edited, relative} = readDates(card);
            if (!dates.size) {
                if (!dedicated.length) out.date_missing_dedicated_node++;
                if (dedicated.some(el => el.children.length)) out.date_missing_nested_node++;
                // Report aggregate structural/date-token patterns only, never raw
                // dates, usernames, review IDs or arbitrary text.
                const shapes = new Set(dedicated.map(el => {
                    const v = txt(el);
                    const tokens = v.match(/수정됨|수정일|수정|일주일|하루|어제|방금|개월|시간|초|분|일|주|달|년|전|\b(?:edited|updated|ago|seconds?|minutes?|hours?|days?|weeks?|months?|years?|a|an|one)\b|\d+|[:：·().\/-]/gi) || [];
                    const safe = tokens.slice(0,12).map(t => /^\d+$/.test(t) ? "#" : t.toLowerCase()).join(" ");
                    return (safe || "NO_DATE_TOKENS") + (edited.test(v) ? " [EDIT_MARKER]" : "");
                }));
                for (const shape of shapes) {
                    if (!(shape in out.date_missing_label_shapes) && Object.keys(out.date_missing_label_shapes).length >= 20) continue;
                    out.date_missing_label_shapes[shape] = (out.date_missing_label_shapes[shape] || 0) + 1;
                }
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
            const scoped = mainBody(card);
            if (scoped.kind === "PRIMARY") {
                if (scoped.text) out.scoped_primary_body_present++;
                else out.scoped_primary_body_blank++;
            } else if (scoped.kind === "FALLBACK_UNVERIFIED") out.scoped_body_fallback_unverified++;
            else if (scoped.kind === "AMBIGUOUS") out.scoped_body_ambiguous++;
            else out.scoped_body_not_detected++;
            if (scoped.kind !== "PRIMARY" || !scoped.text) {
                const reason = scoped.reason || "PRIMARY_BLANK";
                out.unverified_body_structure[reason] = (out.unverified_body_structure[reason] || 0) + 1;
                if (scoped.owner_header_visible) out.unverified_with_owner_header++;
                const absence = scoped.absence_evidence || "OTHER_UNVERIFIED";
                out.body_absence_evidence[absence] = (out.body_absence_evidence[absence] || 0) + 1;
            }
            if (includeRecords) {
                records.push({source_id:id, author:txt(card.querySelector('.d4r55')),
                    rating:ratings.size === 1 ? [...ratings][0] : null,
                    date_label:dates.size === 1 ? [...dates][0] : null,
                    body:scoped.text, body_scope:scoped.kind,
                    body_absence_evidence:scoped.absence_evidence || null,
                    // Diagnostic only: replicate the previous extractor's first
                    // match per selector and longest normalized text. Never use
                    // this broad text as a candidate payload.
                    legacy_body_probe:['.wiI7pd','.MyEned'].map(sel => {
                        const el = card.querySelector(sel);
                        return (el?.innerText || '').replace(/\s+/g,' ').trim();
                    }).sort((a,b) => b.length - a.length)[0] || ""});
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


# Shared selection rule used in extraction, body measurement and fingerprinting.
# A broad .MyEned container may contain controls, details or owner text.
# Only an identifiable visible main .wiI7pd body is considered authoritative.
MAIN_BODY_JS = r"""card => {
    const visible = el => !!el.getClientRects().length;
    const owner = [...card.querySelectorAll('span,div')].find(el =>
        !el.children.length && /^(?:업체 대표 응답|소유자 답변|Response from the owner|Owner response)$/i.test((el.innerText || '').trim()));
    const beforeOwner = el => !el.closest('.CDe7pd,.RfnDt') &&
        (!owner || !!(el.compareDocumentPosition(owner) & Node.DOCUMENT_POSITION_FOLLOWING));
    const bodies = [...card.querySelectorAll('.wiI7pd')].filter(el => visible(el) && beforeOwner(el));
    const unique = bodies.filter(el => !bodies.some(other => other !== el && el.contains(other)));
    if (unique.length === 1) return {kind:"PRIMARY", text:(unique[0].innerText || '').trim()};
    if (unique.length > 1) return {kind:"AMBIGUOUS", text:"", reason:"MULTIPLE_SCOPED_NODES"};
    const fallback = [...card.querySelectorAll('.MyEned')].some(el => visible(el) && beforeOwner(el) && (el.innerText || '').trim());
    const broad = [...card.querySelectorAll('.wiI7pd,.MyEned')];
    const hasText = el => !!(el.innerText || el.textContent || '').trim();
    const reason = fallback ? "BROAD_CONTAINER_ONLY" :
        broad.some(el => visible(el) && hasText(el) && el.closest('.RfnDt') && !el.closest('.CDe7pd')) ? "EXCLUDED_RFNDT_ANCESTOR" :
        broad.some(el => visible(el) && hasText(el) && el.closest('.CDe7pd')) ? "EXCLUDED_OWNER_CONTAINER" :
        broad.some(el => visible(el) && hasText(el) && !beforeOwner(el)) ? "AFTER_OWNER_HEADER" :
        broad.some(el => !visible(el) && hasText(el)) ? "HIDDEN_TEXT_NODE" :
        broad.length ? "BLANK_OR_NO_SCOPED_NODE" : "NO_KNOWN_BODY_NODE";
    // Distinguish structural absence from an excluded or hidden customer body.
    // A visible owner-only section is evidence, not proof of a rating-only review.
    const customerNodes = broad.filter(el => !el.closest('.CDe7pd') &&
        (!owner || !!(el.compareDocumentPosition(owner) & Node.DOCUMENT_POSITION_FOLLOWING)));
    const ownerNodes = broad.filter(el => el.closest('.CDe7pd') && visible(el) && hasText(el));
    const absence = customerNodes.length ? "CUSTOMER_NODE_PRESENT_UNVERIFIED" :
        owner && visible(owner) && ownerNodes.length ? "OWNER_ONLY_KNOWN_NODES" :
        broad.length === 0 ? "NO_KNOWN_TEXT_NODES" : "OTHER_UNVERIFIED";
    return {kind:fallback ? "FALLBACK_UNVERIFIED" : "NOT_DETECTED", text:"", reason,
        owner_header_visible: !!owner && visible(owner), absence_evidence: absence};
}"""


def body_snapshot(card):
    """Measure and fingerprint exactly the same scoped primary text."""
    result = card.evaluate(MAIN_BODY_JS)
    value = result["text"]
    return (len(value), hashlib.sha256(value.encode("utf-8")).digest() if value else None,
            result["kind"])


def body_fingerprint(card):
    return body_snapshot(card)[1]


def body_measure(card):
    return body_snapshot(card)[0]


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


def audit_body_sample(page, store_key, reviews, limit=10, deadline=None):
    """Bounded ordinary UI check on initially loaded cards, aggregate only."""
    cards = page.locator(".jftiEf[data-review-id]")
    n = min(cards.count(), limit)
    initial_ids = cards.evaluate_all("(cards) => cards.map(c => c.getAttribute('data-review-id'))")[:n]
    metrics = dict(sample_cards=n, processed_cards=0, time_budget_reached=False,
                   initial_body_not_detected=0, initial_body_missing_after=0,
                   previously_present_body_lost=0,
                   more_candidates=0, more_confirmed=0,
                   more_length_increased=0, more_no_length_increase=0,
                   more_ambiguous=0, more_control_resolved=0,
                   more_details_increased=0, more_details_only=0,
                   more_closed_without_growth=0, more_remaining=0,
                   original_candidates=0,
                   original_confirmed=0, original_length_changed=0,
                   more_text_changed=0, more_same_length_text_changed=0,
                   original_text_changed=0, original_same_length_text_changed=0,
                   primary_fingerprint_unavailable=0,
                   initial_scope_counts={}, final_scope_counts={},
                   body_missing_after=0, identity_mismatch=0,
                   context_lost=False, click_errors=0,
                   excluded_nonreview_more=0, excluded_nonreview_original=0)
    for i in range(n):
        if deadline is not None and time.monotonic() >= deadline:
            metrics["time_budget_reached"] = True
            break
        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
            metrics["context_lost"] = True
            break
        card = cards.nth(i)
        identity = card.get_attribute("data-review-id")
        if i >= len(initial_ids) or not identity or identity != initial_ids[i]:
            metrics["identity_mismatch"] += 1
            break
        before, before_fingerprint, before_scope = body_snapshot(card)
        metrics["initial_scope_counts"][before_scope] = metrics["initial_scope_counts"].get(before_scope, 0) + 1
        if not before:
            metrics["initial_body_not_detected"] += 1
        if before_fingerprint is None:
            metrics["primary_fingerprint_unavailable"] += 1
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
                    after, after_fingerprint, _ = body_snapshot(card)
                    if before_fingerprint is not None and after_fingerprint is not None and before_fingerprint != after_fingerprint:
                        metrics["more_text_changed"] += 1
                        if after == before:
                            metrics["more_same_length_text_changed"] += 1
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
                    before_original, original_before_fingerprint, _ = body_snapshot(card)
                    original.click(timeout=2500)
                    page.wait_for_timeout(350)
                    if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                        metrics["context_lost"] = True
                        break
                    if card.get_attribute("data-review-id") != identity:
                        metrics["identity_mismatch"] += 1
                        break
                    after_original, original_after_fingerprint, _ = body_snapshot(card)
                    if original_before_fingerprint is not None and original_after_fingerprint is not None and original_before_fingerprint != original_after_fingerprint:
                        metrics["original_text_changed"] += 1
                        if after_original == before_original:
                            metrics["original_same_length_text_changed"] += 1
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
        final_length, _, final_scope = body_snapshot(card)
        metrics["final_scope_counts"][final_scope] = metrics["final_scope_counts"].get(final_scope, 0) + 1
        if not final_length:
            metrics["body_missing_after"] += 1
            if before:
                metrics["previously_present_body_lost"] += 1
            else:
                metrics["initial_body_missing_after"] += 1
        metrics["processed_cards"] += 1
        if deadline is not None and (metrics["processed_cards"] % 25 == 0 or metrics["processed_cards"] == n):
            print("LOCAL_BODY_PROGRESS: " + json.dumps({"processed_cards": metrics["processed_cards"], "target_cards": n}), flush=True)
    metrics["status"] = ("BODY_SAMPLE_TIME_BUDGET_REACHED" if metrics["time_budget_reached"] else body_sample_status(metrics))
    metrics["original_control_evidence"] = (
        "NOT_OBSERVED" if metrics["original_candidates"] == 0 else
        ("CONTROLS_RESOLVED" if metrics["original_confirmed"] == metrics["original_candidates"]
         else "UNRESOLVED")
    )
    # A resolved control is not proof of full text; unchanged-length cases
    # remain explicitly distinguished from demonstrated body growth.
    metrics["full_text_verified"] = False
    metrics["original_language_verified"] = False
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
    normalized = re.sub(r"^(?:수정(?:됨|일)?|edited|updated)\s*[:：·-]?\s*", "", value, flags=re.I)
    normalized = re.sub(r"\s*[·(]?\s*(?:수정(?:됨|일)?|edited|updated)\)?$", "", normalized, flags=re.I)
    normalized = re.sub(r"^한\s*(주|달|개월|년|시간|분|초)\s*전$", r"1\1 전", normalized)
    if normalized in ("어제", "하루 전"):
        age = 1
    elif re.fullmatch(r"일주일\s*전", normalized):
        age = 7
    elif normalized == "방금":
        age = 0
    else:
        age = production.relative_review_age_days(normalized)
    if age is None or age < 0 or age > 36500:
        return None, None
    return (base - timedelta(days=age)).isoformat(), "estimated"


def adapt_local_records(records, store_name, base, production, *, store_id=None):
    """Map transient visible records into the existing engine's candidate shape.

    Only for offline reconciliation. Store display name is diagnostic scope,
    never a substitute for an immutable DB store ID during a real rollout.
    """
    candidates, seen = [], set()
    gaps = dict(invalid_metadata=0, missing_source=0, duplicate_source=0, unverified_body_scope=0)
    for raw in records:
        source = production.hash_google_source_review_id(str(store_id or store_name), raw.get("source_id"))
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
        if raw.get("body_scope") in {"FALLBACK_UNVERIFIED", "AMBIGUOUS", "NOT_DETECTED"} or (raw.get("body_scope") == "PRIMARY" and not raw.get("body")):
            gaps["unverified_body_scope"] += 1
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
    from review_audit_invariants import candidate_partition_ok
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
        observed_unique >= 6
        and metrics["status"] == "REQUIRED_FIELDS_PRESENT"
        and candidate_partition_ok(observed_unique, len(candidates), unique, matched, ready, held, gaps)
        and replay["already_matched"] == 1 and not replay["ready"] and not replay["held"]
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


def read_only_db_config():
    """Explicit local audit credentials only; never fall back to service role."""
    base = os.environ.get("SV_REVIEW_AUDIT_URL", "").strip().rstrip("/")
    key = os.environ.get("SV_REVIEW_AUDIT_API_KEY", "").strip()
    token = os.environ.get("SV_REVIEW_AUDIT_ACCESS_TOKEN", "").strip()
    p = urlsplit(base)
    if not base or not key:
        raise ValueError("AUDIT_DATABASE_CONFIG_MISSING")
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.path or p.query or p.fragment or p.port is not None):
        raise ValueError("AUDIT_DATABASE_URL_INVALID")
    if key.startswith("sb_secret_") or token.startswith("sb_secret_"):
        raise ValueError("AUDIT_PRIVILEGED_KEY_NOT_ALLOWED")
    if not key.startswith("sb_publishable_") and key.count(".") != 2:
        raise ValueError("AUDIT_KEY_FORMAT_UNVERIFIED")
    if token and token.count(".") != 2:
        raise ValueError("AUDIT_TOKEN_FORMAT_UNVERIFIED")
    # A legacy JWT service_role key is also disallowed. This check is a
    # credential hygiene guard, not a replacement for actual DB grants/RLS.
    import base64
    for credential in (key, token):
        if credential.count(".") == 2:
            try:
                payload = credential.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            except Exception:
                raise ValueError("AUDIT_TOKEN_INVALID") from None
            if claims.get("role") not in {"anon", "authenticated"}:
                raise ValueError("AUDIT_PRIVILEGED_KEY_NOT_ALLOWED")
    return base, key, token


def audit_db_get(config, table, params):
    """GET only, table allowlist, no redirects, count of rows visible to caller."""
    from urllib.parse import urlencode
    from urllib.request import Request, build_opener, HTTPRedirectHandler

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    if table not in {"stores", "reviews"}:
        raise ValueError("AUDIT_TABLE_NOT_ALLOWED")
    base, key, token = config
    headers = {"apikey": key, "Accept": "application/json", "Prefer": "count=exact"}
    if token:
        headers["Authorization"] = "Bearer " + token
    elif key.count(".") == 2:
        headers["Authorization"] = "Bearer " + key
    request = Request(base + "/rest/v1/" + table + "?" + urlencode(params),
                      headers=headers, method="GET")
    with build_opener(NoRedirect()).open(request, timeout=45) as response:
        rows = json.loads(response.read().decode("utf-8"))
        content_range = response.headers.get("Content-Range", "")
    match = re.search(r"/(\d+)$", content_range)
    if not isinstance(rows, list) or not match:
        raise ValueError("AUDIT_COUNT_NOT_VERIFIED")
    return rows, int(match.group(1))


def exact_place_pair(url):
    """Strict DB mapping identity; do not accept a substring or another place."""
    from urllib.parse import unquote
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname not in {"www.google.com", "google.com", "maps.google.com"}
                or p.username or p.password or p.port is not None or not p.path.startswith("/maps/place/")):
            return None
        pairs = set(re.findall(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)(?=!|/|$)", unquote(p.path).lower()))
        return next(iter(pairs)) if len(pairs) == 1 else None
    except (TypeError, ValueError):
        return None


def verified_db_store(config, store_key):
    names = {"thailand": ("Saemaeul Central Eastville", "Thailand"),
             "taiwan": ("Bornga Dunnan Store", "Taiwan")}
    registered = STORE_CONFIG[store_key].get("registered_store")
    if registered is not None:
        name, country = registered["name"], registered["country"]
        filters = {"id": "eq." + registered["id"]}
    else:
        name, country = names[store_key]
        filters = {"store_name": "eq." + name, "country": "eq." + country}
    rows, total = audit_db_get(config, "stores", {
        "select": "id,store_name,country,sv,google_maps_url,is_active",
        **filters, "is_active": "eq.true", "limit": "2",
    })
    if total != 1 or len(rows) != 1:
        raise ValueError("AUDIT_STORE_MAPPING_UNVERIFIED")
    row = rows[0]
    from uuid import UUID
    try:
        UUID(str(row.get("id")))
    except (TypeError, ValueError):
        raise ValueError("AUDIT_STORE_ID_INVALID") from None
    if (row.get("store_name") != name or row.get("country") != country
            or (registered is not None and str(row.get("id")) != registered["id"])
            or row.get("is_active") is not True
            or not isinstance(row.get("google_maps_url"), str)
            or not exact_place_pair(STORE_CONFIG[store_key]["url"])
            or exact_place_pair(row["google_maps_url"]) != exact_place_pair(STORE_CONFIG[store_key]["url"])):
        raise ValueError("AUDIT_STORE_IDENTITY_MISMATCH")
    return row


def load_visible_history(config, store):
    """Require consistent exact count and distinct row IDs across pages.

    This is not a transactional snapshot or proof of unrestricted RLS access.
    """
    rows, ids, expected = [], set(), None
    while True:
        batch, total = audit_db_get(config, "reviews", {
            "select": "id,store_id,store_name,author,rating,text,review_text,date,relative_date,review_date,review_key,has_text",
            "store_id": "eq." + str(store["id"]), "order": "id.asc",
            "limit": "500", "offset": str(len(rows)),
        })
        if expected is None:
            expected = total
        if total != expected or expected > 20000:
            raise ValueError("AUDIT_HISTORY_COUNT_CHANGED_OR_LIMIT")
        for row in batch:
            row_id = row.get("id")
            if not row_id or row_id in ids or row.get("store_id") != store["id"]:
                raise ValueError("AUDIT_HISTORY_IDENTITY_MISMATCH")
            ids.add(row_id)
            rows.append(normalize_history_row(row))
        if len(rows) == expected:
            return rows
        if not batch or len(rows) > expected:
            raise ValueError("AUDIT_HISTORY_INCOMPLETE")


def normalize_history_row(row):
    """Preserve legacy text in memory; reject conflicting dual fields."""
    normalized = dict(row)
    for current, legacy in (("text", "review_text"), ("date", "relative_date")):
        a, b = row.get(current), row.get(legacy)
        if any(value is not None and not isinstance(value, str) for value in (a, b)):
            raise ValueError("AUDIT_HISTORY_FIELD_TYPE_INVALID")
        if a and a.strip() and b and b.strip() and a.strip() != b.strip():
            raise ValueError("AUDIT_HISTORY_FIELD_CONFLICT")
        normalized[current] = a if a and a.strip() else (b or "")
    return normalized


def db_read_preflight(store_key):
    config = read_only_db_config()
    store = verified_db_store(config, store_key)
    rows = load_visible_history(config, store)
    keys = [row.get("review_key") for row in rows]
    if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("AUDIT_HISTORY_KEY_UNVERIFIED")
    return {"status": "DB_READ_PREFLIGHT_PASSED", "store": store["store_name"],
            "visible_existing_rows": len(rows), "distinct_keys": len(set(keys)),
            "body_present": sum(bool(row["text"].strip()) for row in rows),
            "history_visibility": "CALLER_VISIBLE_ONLY", "database_writes": False,
            "production_ready": False}


MAX_COUNT_DB_AUDIT = 1000
MAX_COUNT_BODY_AUDIT = 250
COUNT_BODY_SECONDS = 900


def count_body_evidence(metrics, expected):
    """Review-control evidence, not a claim of full text or original language."""
    if metrics["context_lost"] or metrics["identity_mismatch"]:
        return "COUNT_BODY_CONTEXT_LOST"
    if metrics["time_budget_reached"] or metrics["processed_cards"] != expected:
        return "COUNT_BODY_INCOMPLETE"
    if (metrics["click_errors"] or metrics["previously_present_body_lost"]
            or metrics["more_control_resolved"] != metrics["more_candidates"]
            or metrics["original_confirmed"] != metrics["original_candidates"]):
        return "COUNT_BODY_CONTROL_GAPS"
    if (metrics["more_closed_without_growth"] or metrics["more_details_only"]
            or metrics["original_confirmed"] != metrics["original_text_changed"]
            or metrics["body_missing_after"] or metrics["primary_fingerprint_unavailable"]):
        return "COUNT_BODY_EVIDENCE_LIMITED"
    return "COUNT_BODY_CONTROLS_CHECKED"


def verified_record_set(records, expected_seen):
    """Count equality alone does not prove the same cards remain loaded."""
    ids = [r.get("source_id") for r in records]
    if any(not isinstance(i, str) or not i for i in ids):
        return False
    digests = {hashlib.sha256(i.encode("utf-8")).digest() for i in ids}
    return len(ids) == len(digests) == len(expected_seen) and digests == expected_seen


def match_evidence(records, history, production):
    """Aggregate-only diagnosis, not a replacement matcher or write approval."""
    from collections import Counter, defaultdict
    import unicodedata
    def norm(value):
        return production.normalize_spaces(value or "").casefold()
    def script(value):
        if not value:
            return "EMPTY"
        has_thai = any("\u0e00" <= c <= "\u0e7f" for c in value)
        has_hangul = any("\uac00" <= c <= "\ud7a3" for c in value)
        has_latin = any("LATIN" in unicodedata.name(c, "") for c in value)
        return "+".join(k for k, v in (("THAI",has_thai),("HANGUL",has_hangul),("LATIN",has_latin)) if v) or "OTHER"
    by_author = defaultdict(list)
    for row in history:
        by_author[norm(row.get("author"))].append(row)
    live_pairs = Counter((norm(r.get("author")), r.get("rating")) for r in records)
    counts = Counter()
    legacy_counts = Counter()
    legacy_scripts = Counter()
    live_scripts = Counter()
    saved_scripts = Counter(script(row.get("text")) for row in history)
    for raw in records:
        body = raw.get("body") or ""
        scoped = raw.get("body_scope") == "PRIMARY" and bool(body.strip())
        if scoped:
            live_scripts[script(body)] += 1
        same_author = by_author.get(norm(raw.get("author")), [])
        same_rating = [row for row in same_author if row.get("rating") == raw.get("rating")]
        counts["observed"] += 1
        if not same_author:
            counts["no_author_match"] += 1
        elif not same_rating:
            counts["author_only"] += 1
        elif len(same_rating) == 1:
            counts["unique_author_rating_candidate"] += 1
        else:
            counts["multiple_author_rating_candidates"] += 1
        if len(same_rating) == 1 and live_pairs[(norm(raw.get("author")), raw.get("rating"))] == 1:
            counts["one_to_one_author_rating_candidate"] += 1
        if same_rating and not scoped:
            counts["author_rating_body_unverified"] += 1
        legacy = raw.get("legacy_body_probe") or ""
        if legacy:
            legacy_scripts[script(legacy)] += 1
        if legacy and same_author:
            exact = [row for row in same_author if norm(row.get("text")) == norm(legacy)]
            if exact:
                legacy_counts["broad_exact_author_body"] += 1
                if any(row.get("rating") == raw.get("rating") for row in exact):
                    legacy_counts["broad_exact_author_rating_body"] += 1
                if not scoped or norm(legacy) != norm(body):
                    legacy_counts["broad_match_not_same_as_scoped"] += 1
            elif same_rating and any(
                production.normalized_review_text_for_match(row.get("text")) and
                production.normalized_review_text_for_match(row.get("text")) == production.normalized_review_text_for_match(legacy)
                for row in same_rating
            ):
                legacy_counts["broad_punctuation_insensitive_candidate"] += 1
        if same_rating and scoped:
            if any(norm(row.get("text")) == norm(body) for row in same_rating):
                counts["author_rating_exact_body"] += 1
            else:
                counts["author_rating_different_body"] += 1
                if all(script(row.get("text")) != script(body) for row in same_rating):
                    counts["different_script_group"] += 1
    return {"counts": dict(counts), "live_scoped_body_scripts": dict(live_scripts),
            "history_body_scripts": dict(saved_scripts),
            "legacy_extractor_shadow_counts": dict(legacy_counts),
            "legacy_extractor_shadow_scripts": dict(legacy_scripts),
            "legacy_shadow_is_diagnostic_only": True,
            "history_canonical_key_matches": sum(row.get("review_key") == production.canonical_review_hash(row) for row in history),
            "history_rows": len(history), "identity_confirmed_by_metadata": False,
            "write_approved": False}


def source_identity_preview(records, history, store_id, production):
    """One-to-one exact-text linkage proposal only, without persisting identifiers.

    A Google source hash does not exist on historical rows. Exact scoped text,
    author and rating offer linkage evidence, not proof of identity. Reject
    duplicate source IDs and shared historical targets across all live cards.
    """
    from collections import Counter, defaultdict
    def normalized(value):
        return production.normalize_spaces(value or "").casefold()
    def key(author, rating, body):
        return normalized(author), rating, normalized(body)
    saved = defaultdict(list)
    for row in history:
        k = key(row.get("author"), row.get("rating"), row.get("text"))
        if k[0] and k[0] not in {"anonymous","unknown"} and k[2] and row.get("id"):
            saved[k].append(row["id"])
    sources = [production.hash_google_source_review_id(str(store_id), r.get("source_id")) for r in records]
    source_counts = Counter(sources)
    possibilities = []
    categories = Counter()
    for raw, source in zip(records, sources):
        if not source or source_counts[source] != 1:
            categories["invalid_or_duplicate_source"] += 1
            continue
        if raw.get("body_scope") != "PRIMARY" or not normalized(raw.get("body")):
            categories["body_unverified"] += 1
            continue
        k = key(raw.get("author"), raw.get("rating"), raw.get("body"))
        targets = saved.get(k, [])
        if len(targets) != 1:
            categories["no_exact_target" if not targets else "multiple_exact_targets"] += 1
            continue
        possibilities.append(targets[0])
    target_counts = Counter(possibilities)
    for target in possibilities:
        categories["one_to_one_exact_proposal" if target_counts[target] == 1 else "shared_target_held"] += 1
    return {"counts": dict(categories), "observed": len(records),
            "classified": sum(categories.values()), "balanced": sum(categories.values()) == len(records),
            "stable_source_id_available_in_dom": sum(bool(source) for source in sources),
            "identity_verified": False, "links_persisted": 0, "write_approved": False}


def verified_record_order(records, expected_order):
    ids = [r.get("source_id") for r in records]
    if any(not isinstance(i,str) or not i for i in ids):
        return False
    digests = [hashlib.sha256(i.encode("utf-8")).hexdigest() for i in ids]
    return len(digests)==len(set(digests)) and digests==expected_order


def compare_db_sample(page, store_key, observed_unique, *, expected_seen=None, expected_order=None):
    import scraper as production
    from review_append_preflight import preview_append
    from review_source_append_preview import simulate_append_replay
    from review_audit_invariants import candidate_partition_ok, preview_partition_ok, diagnostic_partition
    is_count_audit = expected_seen is not None
    is_order_audit = expected_order is not None
    metrics, records = audit_loaded_fields(page, observed_unique, include_records=True)
    if is_order_audit and (not is_count_audit or not 30 <= observed_unique <= 300
                           or not verified_record_order(records, expected_order)):
        return {"status":"NEWEST_DB_CARD_ORDER_UNVERIFIED","actual_database_compared":False,
                "database_writes":False,"write_approved":False}
    if is_count_audit and (not 1 <= observed_unique <= MAX_COUNT_DB_AUDIT
                           or not verified_record_set(records, expected_seen)
                           or metrics["duplicate_cards"]
                           or metrics["status"] != "REQUIRED_FIELDS_PRESENT"):
        return {
            "status": "COUNT_DB_AUDIT_CARD_SET_UNVERIFIED",
            "observed_unique": observed_unique,
            "actual_database_compared": False, "database_writes": False,
            "full_text_verified": False, "full_coverage_verified": False,
            "write_approved": False,
        }
    config = read_only_db_config()
    store = verified_db_store(config, store_key)
    saved = load_visible_history(config, store)
    candidates, gaps = adapt_local_records(
        records, store["store_name"], production.now_kst().date(), production,
        store_id=store["id"]
    )
    historical = [dict(row, store_name=store["store_name"], text=row.get("text") or "") for row in saved]
    plan = production.plan_safe_review_append(historical, candidates)
    append_preview = preview_append(store, saved, candidates, production)
    partition = diagnostic_partition(observed_unique, len(candidates), gaps, append_preview)
    unique = len(plan["unique_candidates"])
    matched = plan["already_matched"]
    ready, held = len(plan["ready"]), len(plan["held"])
    consistent = (
        observed_unique >= (1 if is_count_audit else 6)
        and metrics["status"] == "REQUIRED_FIELDS_PRESENT"
        and not metrics["duplicate_cards"]
        and candidate_partition_ok(observed_unique, len(candidates), unique, matched, ready, held, gaps)
        and preview_partition_ok(append_preview)
        and partition["status"] == "PARTITION_BALANCED"
    )
    return {
        "status": ("LOCAL_COUNT_DB_COMPARED" if consistent else "LOCAL_COUNT_DB_GAPS")
                  if is_count_audit else ("LOCAL_DB_SAMPLE_COMPARED" if consistent else "LOCAL_DB_SAMPLE_GAPS"),
        "scope": "NEWEST_ORDERED_DOM" if is_order_audit else ("COUNT_MATCHED_DOM" if is_count_audit else "INITIAL_SAMPLE"),
        "same_card_order_verified": is_order_audit,
        "same_card_set_verified": is_count_audit,
        "body_unexpanded_possible": metrics["possible_collapsed_body"],
        "classification_balanced": partition["status"] == "PARTITION_BALANCED",
        "strict_adapter_preflight_passed": consistent,
        "store_mapping_verified": True,
        "visible_existing_rows": len(saved),
        "observed_unique": observed_unique, "adapted_candidates": len(candidates),
        "metadata_gaps": gaps, "legacy_unique_candidates": unique,
        "legacy_key_collapses": len(candidates) - unique,
        "matched_existing": matched, "potential_new_unapproved": ready,
        "held_for_review": held, "held_reasons": plan["held_reasons"],
        "append_preview": append_preview,
        "diagnostic_partition": partition,
        "match_evidence": match_evidence(records, historical, production),
        "source_identity_preview": source_identity_preview(records, historical, store["id"], production),
        "source_append_replay_simulation": simulate_append_replay(store, saved, candidates, production),
        "body_absence_evidence": metrics["body_absence_evidence"],
        "unverified_body_structure": metrics["unverified_body_structure"],
        "actual_database_compared": True, "database_writes": False,
        "history_visibility": "CALLER_VISIBLE_ONLY",
        "transactional_snapshot_verified": False,
        "full_text_verified": False, "full_coverage_verified": False,
        "write_approved": False,
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


MAX_EXPECTED_COUNT = 10000
MAX_COUNT_ROUNDS = 5000
MAX_COUNT_SECONDS = 10800


def scaled_count_budget(total, rounds, seconds, enabled=False):
    """Optional conservative planning estimate; never increases scroll cadence."""
    if (type(total) is not int or not 1 <= total <= MAX_EXPECTED_COUNT
            or not 1 <= rounds <= MAX_COUNT_ROUNDS
            or not 1 <= seconds <= MAX_COUNT_SECONDS):
        raise ValueError("COUNT_BUDGET_OUT_OF_SCOPE")
    if not enabled:
        return rounds, seconds
    # Plan for only two new IDs per scroll round, with startup/no-growth margin.
    estimated = (total + 1) // 2 + 40
    return (min(MAX_COUNT_ROUNDS, max(rounds, estimated)),
            min(MAX_COUNT_SECONDS, max(seconds, estimated * 4)))


def count_budget_status(rounds, elapsed, round_limit, second_limit):
    if elapsed >= second_limit:
        return "TIME_BUDGET_REACHED"
    if rounds >= round_limit:
        return "ROUND_LIMIT"
    return None


def maps_language_url(url, language):
    """Use the ordinary Maps display-language parameter, preserving place path."""
    if language == "profile":
        return url
    if language != "en":
        raise ValueError("MAPS_LANGUAGE_UNSUPPORTED")
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "hl"]
    query.append(("hl", "en"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def run_once(context, expected_total=None, store_key="thailand", auto_total=False, scroll_mode="baseline", audit_fields=False, field_sample=False, body_sample=False, adapter_sample=False, db_sample=False, count_round_limit=240, count_second_limit=600, count_db_audit=False, count_body_audit=False, maps_language="profile", scale_count_budget=False, newest_heads=None, newest_db_audit=False):
    report = {"status": "NOT_STARTED", "phase": "select_startup_tab",
              "overview_selected": False,
              "reviews_selected": False, "initial_unique": 0,
              "observed_unique": 0, "additional_unique": 0, "scroll_rounds": 0,
              "scroll_verified": False, "database_writes": False,
              "full_coverage_verified": False}
    report["store"] = STORE_CONFIG[store_key]["name"]
    if newest_db_audit and newest_heads is None:
        raise ValueError("NEWEST_DB_AUDIT_REQUIRES_HEAD")
    if newest_heads is not None and (maps_language != "en" or auto_total or expected_total is not None or audit_fields or field_sample or body_sample or adapter_sample or db_sample or count_db_audit or count_body_audit):
        raise ValueError("NEWEST_SAMPLE_SCOPE_INVALID")
    report["maps_language_requested"] = maps_language
    report["maps_ui_language"] = "UNVERIFIED"
    if maps_language not in {"profile", "en"} or (auto_total and expected_total is not None):
        raise ValueError("MAPS_LANGUAGE_SCOPE_INVALID")
    if scale_count_budget and (not (auto_total or expected_total is not None) or count_db_audit or count_body_audit):
        raise ValueError("SCALED_BUDGET_COUNT_ONLY")
    if count_body_audit and (expected_total is None or not 1 <= expected_total <= MAX_COUNT_BODY_AUDIT
                             or auto_total or field_sample or body_sample or adapter_sample or db_sample):
        raise ValueError("COUNT_BODY_AUDIT_SCOPE_INVALID")
    if count_body_audit:
        audit_fields = True
    if count_db_audit and (store_key not in {"thailand", "taiwan"} or expected_total is None
                           or not 1 <= expected_total <= MAX_COUNT_DB_AUDIT
                           or auto_total or field_sample or body_sample or adapter_sample or db_sample):
        raise ValueError("COUNT_DB_AUDIT_SCOPE_INVALID")
    if expected_total is not None:
        report["expected_total_user_observed"] = expected_total
        report["additional_unique"] = 0
        report["stop_reason"] = None
    if expected_total is not None or auto_total:
        if not 1 <= count_round_limit <= MAX_COUNT_ROUNDS or not 1 <= count_second_limit <= MAX_COUNT_SECONDS:
            raise ValueError("COUNT_BUDGET_OUT_OF_SCOPE")
        if expected_total is not None and not 1 <= expected_total <= MAX_EXPECTED_COUNT:
            raise ValueError("EXPECTED_COUNT_OUT_OF_SCOPE")
        report["count_round_limit"] = count_round_limit
        report["count_second_limit"] = count_second_limit
    report["scale_count_budget_requested"] = scale_count_budget
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
        if store_key == "thailand" and auto_total and maps_language == "profile":
            failure = find_store_by_search(page, report)
            if failure:
                report["status"] = failure
                return report
        else:
            report["phase"] = "open_configured_store"
            report["entry_method"] = "repository_store_url"
            page.goto(maps_language_url(STORE_CONFIG[store_key]["url"], maps_language), wait_until="domcontentloaded", timeout=45000)
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
        overview_label = overview.inner_text().strip()
        reviews_label = reviews.inner_text().strip()
        if overview_label.casefold() == "overview" and re.fullmatch(r"reviews(?:\s*\(?[\d,]+\)?)?", reviews_label, re.I):
            report["maps_ui_language"] = "ENGLISH"
        elif overview_label == "개요" and re.fullmatch(r"리뷰(?:\s*\(?[\d,]+\)?)?", reviews_label):
            report["maps_ui_language"] = "KOREAN"
        else:
            report["maps_ui_language"] = "MIXED_OR_UNVERIFIED"
        if maps_language == "en" and report["maps_ui_language"] != "ENGLISH":
            report["status"] = "REQUESTED_MAPS_LANGUAGE_NOT_VERIFIED"
            return report
        report["overview_selected"] = selected(overview)
        report["reviews_selected_at_entry"] = selected(reviews)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        if not same_place(page.url, store_key):
            report["status"] = "PLACE_NOT_VERIFIED"
            return report

        # Never leave a verified Reviews tab just to read the count.
        # Direct links can also finish an asynchronous tab transition.
        report["overview_total"] = {"status":"NOT_OBSERVED","displayed_total":None,"candidate_counts":[]}
        overview_target = None
        if selected(reviews):
            report["total_entry_path"] = "reviews_direct"
        elif selected(overview):
            report["total_entry_path"] = "overview"
            report["phase"] = "read_overview_total"
            report["overview_total"] = displayed_total(page)
            if auto_total:
                page.wait_for_timeout(1200)
                if blocked(page):
                    report["status"] = "ACCESS_RESTRICTED_STOPPED"
                    return report
                if not same_place(page.url, store_key):
                    report["status"] = "REVIEW_CONTEXT_LOST"
                    return report
                if selected(overview) and not selected(reviews):
                    second = displayed_total(page)
                    report["overview_total_recheck"] = second
                    overview_target = stable_overview_total(report["overview_total"], second)
            if not selected(reviews):
                if not selected(overview):
                    report["status"] = "ENTRY_TAB_NOT_VERIFIED"
                    return report
                report["phase"] = "select_reviews"
                reviews.click(timeout=5000)
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

        if newest_heads is not None:
            report["phase"] = "verify_newest_sort"
            report["newest_sort_evidence"] = []
            report["newest_sort_status"] = verify_newest_sort(page, store_key, reviews, report["newest_sort_evidence"])
            if report["newest_sort_status"] not in {"NEWEST_SORT_UI_VERIFIED","NEWEST_SORT_ACTION_OBSERVED_ONLY"}:
                report["status"] = report["newest_sort_status"]
                return report
        if auto_total:
            expected_total = overview_target
            total_source = "overview_rating_summary_rechecked"
            if expected_total is None:
                report["phase"] = "read_reviews_total"
                # Allow the rating summary to settle, without leaving Reviews.
                for _ in range(8):
                    if blocked(page):
                        report["status"] = "ACCESS_RESTRICTED_STOPPED"
                        return report
                    if not same_place(page.url, store_key) or not selected(reviews):
                        report["status"] = "REVIEW_CONTEXT_LOST"
                        return report
                    first = displayed_reviews_total(page)
                    report["reviews_total"] = first
                    page.wait_for_timeout(1200)
                    if blocked(page):
                        report["status"] = "ACCESS_RESTRICTED_STOPPED"
                        return report
                    if not same_place(page.url, store_key) or not selected(reviews):
                        report["status"] = "REVIEW_CONTEXT_LOST"
                        return report
                    second = displayed_reviews_total(page)
                    report["reviews_total_recheck"] = second
                    expected_total = stable_overview_total(first, second)
                    if expected_total is not None:
                        break
                total_source = "reviews_rating_summary_rechecked"
            if expected_total is None or not 1 <= expected_total <= MAX_EXPECTED_COUNT:
                report["status"] = "DISPLAYED_TOTAL_NOT_VERIFIED_OR_OUT_OF_SCOPE"
                return report
            report["expected_total_user_observed"] = expected_total
            report["expected_total_source"] = total_source
            report["additional_unique"] = 0
            report["stop_reason"] = None

        page.wait_for_timeout(3000)
        if blocked(page):
            report["status"] = "ACCESS_RESTRICTED_STOPPED"
            return report
        if not selected(reviews) or not same_place(page.url, store_key):
            report["status"] = "REVIEW_CONTEXT_LOST"
            return report

        if expected_total is not None:
            count_round_limit, count_second_limit = scaled_count_budget(expected_total, count_round_limit, count_second_limit, scale_count_budget)
            report["count_round_limit"] = count_round_limit
            report["count_second_limit"] = count_second_limit
        report["phase"] = "wait_for_review_cards"
        def read_initial():
            if blocked(page):
                return "ACCESS_RESTRICTED_STOPPED", {}
            if not same_place(page.url, store_key) or not selected(reviews):
                return "REVIEW_CONTEXT_LOST", {}
            return None, initial_card_evidence(page)
        wait_started = time.monotonic()
        reveal_results = []
        def reveal():
            reveal_results.append(reveal_initial_cards(page, store_key, reviews))
        initial_status, polls_waited, evidence = initial_card_poll(
            read_initial, lambda: page.wait_for_timeout(1000), reveal=reveal)
        report["initial_card_wait"] = {
            "status": initial_status, "poll_intervals": polls_waited,
            "elapsed_seconds": round(time.monotonic() - wait_started, 1),
            "configured_wait_seconds": 45, "evidence": evidence,
            "summary_reveal_results": reveal_results,
            "summary_wheel_rounds": reveal_results.count("SUMMARY_PANE_WHEEL")}
        if initial_status != "INITIAL_REVIEW_CARDS_VISIBLE":
            report["status"] = initial_status
            return report
        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
            report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
            return report

        report["phase"] = "observe_initial_reviews"
        report["initial_unique"], _ = observe(page, seen, id_cache)
        report["observed_unique"] = len(seen)
        if newest_heads is not None:
            report["phase"] = "newest_order_sample"
            first = ordered_head(page)
            if not first:
                report["status"] = "NEWEST_HEAD_UNVERIFIED"
                return report
            prior = first
            sample_started = time.monotonic()
            for i in range(25):
                if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                    report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
                    return report
                current = ordered_head(page)
                if not ordered_extension(prior, current):
                    report["status"] = "NEWEST_HEAD_ORDER_CHANGED"
                    return report
                prior = current
                report["observed_unique"] = len(current)
                report["additional_unique"] = len(current) - report["initial_unique"]
                report["scroll_verified"] = report["additional_unique"] > 0 and report["scroll_rounds"] > 0
                if len(current) >= 30:
                    page.wait_for_timeout(1800)
                    if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                        report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
                        return report
                    final = ordered_head(page)
                    if not ordered_extension(current, final):
                        report["status"] = "NEWEST_HEAD_ORDER_CHANGED"
                        return report
                    dated_head, labels = ordered_date_sample(page)
                    if not ordered_extension(final, dated_head):
                        report["status"] = "NEWEST_HEAD_ORDER_CHANGED"
                        return report
                    report["observed_unique"] = len(dated_head)
                    report["additional_unique"] = len(dated_head) - report["initial_unique"]
                    report["scroll_verified"] = report["additional_unique"] > 0 and report["scroll_rounds"] > 0
                    report["newest_date_evidence"] = displayed_age_evidence(labels[:30])
                    report["newest_date_evidence"]["unique_date_labels_extracted"] = sum(x is not None for x in labels[:30])
                    report["newest_selection_explicit"] = report["newest_sort_status"] == "NEWEST_SORT_UI_VERIFIED"
                    if not report["newest_date_evidence"]["displayed_order_consistent"]:
                        report["status"] = "NEWEST_DISPLAYED_ORDER_INCONCLUSIVE"
                        return report
                    report["newest_head_size"] = 30
                    report["newest_head_sample_verified"] = True
                    newest_heads.append(final[:30])
                    if newest_db_audit and len(newest_heads)==2 and newest_heads[0]==newest_heads[1]:
                        report["phase"] = "newest_head_db_preview"
                        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                            report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
                            return report
                        # Inspect only already-loaded cards with the existing bounded
                        # body-control audit. Never interpret missing body as rating-only.
                        if len(dated_head)>MAX_COUNT_BODY_AUDIT:
                            report["status"] = "NEWEST_BODY_AUDIT_OUT_OF_SCOPE"
                            return report
                        report["phase"] = "newest_head_body_audit"
                        body = audit_body_sample(page, store_key, reviews, limit=len(dated_head),
                                                 deadline=time.monotonic()+min(COUNT_BODY_SECONDS,180))
                        report["newest_body_audit"] = body
                        body_status = count_body_evidence(body,len(dated_head))
                        report["newest_body_audit_status"] = body_status
                        if blocked(page) or not same_place(page.url,store_key) or not selected(reviews):
                            report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
                            return report
                        if ordered_head(page)!=dated_head or body_status in {"COUNT_BODY_CONTEXT_LOST","COUNT_BODY_INCOMPLETE"}:
                            report["status"] = "NEWEST_BODY_AUDIT_HELD"
                            return report
                        report["phase"] = "newest_head_db_preview"
                        # Compare all retained cards from the same ordered snapshot
                        # (may include more than 30), not a separate random sample.
                        report["newest_db_preview"] = compare_db_sample(
                            page, store_key, len(dated_head),
                            expected_seen={bytes.fromhex(h) for h in dated_head},
                            expected_order=dated_head)
                        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                            report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
                            return report
                        if ordered_head(page)!=dated_head or report["newest_db_preview"]["status"]!="LOCAL_COUNT_DB_COMPARED":
                            report["status"] = "NEWEST_DB_PREVIEW_HELD"
                            return report
                    report["status"] = "NEWEST_HEAD_SAMPLE_VERIFIED"
                    report["newest_head_size"] = 30
                    return report
                if i == 24 or time.monotonic()-sample_started >= 60:
                    break
                pane = review_pane(page)
                if pane is None:
                    break
                try:
                    box = pane.bounding_box()
                    if not box:
                        break
                    x,y = box["x"]+box["width"]/2, box["y"]+box["height"]/2
                    if not pane.evaluate("(el,p)=>el.contains(document.elementFromPoint(p.x,p.y))",{"x":x,"y":y}):
                        break
                finally:
                    pane.dispose()
                page.mouse.move(x,y)
                page.mouse.wheel(0,900)
                page.wait_for_timeout(1800)
                report["scroll_rounds"] = i+1
            report["status"] = "NEWEST_HEAD_SAMPLE_INCOMPLETE"
            return report
        if field_sample or body_sample or adapter_sample or db_sample:
            report["phase"] = "initial_field_sample"
            report["field_audit"] = audit_loaded_fields(page, len(seen))
            report["status"] = (
                "FIELD_SAMPLE_VERIFIED"
                if len(seen) >= 6 and report["field_audit"]["status"] == "REQUIRED_FIELDS_PRESENT"
                else "FIELD_SAMPLE_GAPS"
            )
            if db_sample and report["status"] == "FIELD_SAMPLE_VERIFIED":
                report["phase"] = "local_db_sample"
                if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                    report["status"] = "DB_SAMPLE_CONTEXT_UNVERIFIED"
                    return report
                report["db_sample"] = compare_db_sample(page, store_key, len(seen))
                report["status"] = report["db_sample"]["status"]
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
        stall_wait_used = False
        report["stall_observations"] = []
        scroll_started = time.monotonic()
        report["phase"] = "scroll_review_pane"
        max_rounds = count_round_limit if expected_total is not None else 8
        for i in range(1, max_rounds + 1):
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if not same_place(page.url, store_key) or not selected(reviews):
                report["status"] = "REVIEW_CONTEXT_LOST"
                return report
            if expected_total is not None:
                if len(seen) >= expected_total:
                    report["stop_reason"] = "EXPECTED_TOTAL_REACHED" if len(seen) == expected_total else "EXPECTED_TOTAL_EXCEEDED"
                    break
                budget = count_budget_status(i - 1, time.monotonic() - scroll_started,
                                             count_round_limit, count_second_limit)
                if budget:
                    report["stop_reason"] = budget
                    break
            pane = review_pane(page)
            if pane is None:
                if expected_total is not None:
                    report["stop_reason"] = "NO_REVIEW_SCROLL_PANE"
                break
            try:
                box = pane.bounding_box()
                if not box:
                    if expected_total is not None:
                        report["stop_reason"] = "NO_REVIEW_PANE_BOUNDS"
                    break
                before_top = pane.evaluate("(el) => el.scrollTop")
            finally:
                pane.dispose()
            # Use the ordinary visible review list and normal mouse scrolling.
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
            if blocked(page):
                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                return report
            if not same_place(page.url, store_key) or not selected(reviews):
                report["status"] = "REVIEW_CONTEXT_LOST"
                return report
            report["observed_unique"], retained = observe(page, seen, id_cache)
            report["append_only_retained"] = report["append_only_retained"] and retained
            report["additional_unique"] = len(seen) - report["initial_unique"]
            after_pane = review_pane(page)
            try:
                geometry = pane_geometry(after_pane)
                after_top = geometry["top"] if geometry is not None else before_top
            finally:
                if after_pane is not None:
                    after_pane.dispose()
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
                    report["stop_reason"] = "EXPECTED_TOTAL_REACHED" if len(seen) == expected_total else "EXPECTED_TOTAL_EXCEEDED"
                    break
            elif fresh_depth_status(report["initial_unique"], len(seen)) == "REVIEW_DEPTH_VERIFIED":
                break
            idle = 0 if advanced else idle + 1
            if idle >= (4 if expected_total is not None else 3):
                if expected_total is not None:
                    evidence = initial_card_evidence(page)
                    event = {"round": i, "unique": len(seen), "geometry": geometry,
                             "ui": evidence, "state": stall_evidence_status(
                                 geometry, evidence["visible_busy_nodes"]),
                             "passive_wait_used": False}
                    report["stall_observations"].append(event)
                    # One passive observation window for the entire run.
                    # No reload, filter change, extra wheel, or bypass.
                    if not stall_wait_used:
                        stall_wait_used = True
                        event["passive_wait_used"] = True
                        stall_before = len(seen)
                        for _ in range(15):
                            if count_budget_status(i, time.monotonic()-scroll_started,
                                                   count_round_limit, count_second_limit):
                                break
                            page.wait_for_timeout(1000)
                            if blocked(page):
                                report["status"] = "ACCESS_RESTRICTED_STOPPED"
                                return report
                            if not same_place(page.url, store_key) or not selected(reviews):
                                report["status"] = "REVIEW_CONTEXT_LOST"
                                return report
                            report["observed_unique"], retained = observe(page, seen, id_cache)
                            report["append_only_retained"] = report["append_only_retained"] and retained
                            report["additional_unique"] = len(seen) - report["initial_unique"]
                            if len(seen) > stall_before:
                                break
                        event["after_wait_unique"] = len(seen)
                        event["after_wait_ui"] = initial_card_evidence(page)
                        final_pane = review_pane(page)
                        try:
                            event["after_wait_geometry"] = pane_geometry(final_pane)
                        finally:
                            if final_pane is not None:
                                final_pane.dispose()
                        if len(seen) > stall_before:
                            idle = 0
                            continue
                    report["stop_reason"] = "NO_FURTHER_SCROLL_OR_NEW_IDS"
                break

        report["elapsed_scroll_seconds"] = round(time.monotonic() - scroll_started, 1)
        report["phase"] = "final_depth_check"
        if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
            report["status"] = "ACCESS_RESTRICTED_STOPPED" if blocked(page) else "REVIEW_CONTEXT_LOST"
            return report
        if expected_total is not None:
            report["stop_reason"] = report["stop_reason"] or "ROUND_LIMIT"
            report["status"] = coverage_status(len(seen), expected_total, blocked(page))
            report["count_gap"] = expected_total - len(seen)
            report["count_evidence"] = "USER_OR_UI_TOTAL_COMPARISON_ONLY"
            report["expected_count_matched"] = report["status"] == "EXPECTED_COUNT_MATCHED"
        else:
            report["status"] = fresh_depth_status(
                report["initial_unique"], len(seen), blocked(page)
            )
        if audit_fields and report["status"] == "EXPECTED_COUNT_MATCHED":
            report["phase"] = "audit_loaded_fields"
            if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                report["status"] = "FIELD_AUDIT_CONTEXT_UNVERIFIED"
                return report
            report["field_audit"] = audit_loaded_fields(page, len(seen))
            if report["field_audit"]["status"] != "REQUIRED_FIELDS_PRESENT":
                report["status"] = "COUNT_MATCHED_FIELD_GAPS"
            report["phase"] = "final_field_audit"
        diagnostic_date_gaps = (count_body_audit and not count_db_audit
                                and report["status"] == "COUNT_MATCHED_FIELD_GAPS"
                                and report["field_audit"]["author_present"] == len(seen)
                                and report["field_audit"]["rating_valid"] == len(seen)
                                and report["field_audit"]["unique_cards"] == len(seen)
                                and not report["field_audit"]["duplicate_cards"])
        if (count_db_audit or count_body_audit) and (report["status"] == "EXPECTED_COUNT_MATCHED" or diagnostic_date_gaps):
            report["phase"] = "count_matched_db_audit"
            if blocked(page) or not same_place(page.url, store_key) or not selected(reviews):
                report["status"] = "COUNT_DB_AUDIT_CONTEXT_UNVERIFIED"
                return report
            if not report["append_only_retained"]:
                report["status"] = "COUNT_DB_AUDIT_CARD_SET_UNVERIFIED"
                return report
            if count_body_audit:
                report["phase"] = "count_matched_body_audit"
                _, before_records = audit_loaded_fields(page, len(seen), include_records=True)
                same_set = verified_record_set(before_records, seen)
                del before_records
                if not same_set:
                    report["status"] = "COUNT_BODY_AUDIT_CARD_SET_UNVERIFIED"
                    return report
                report["body_sample"] = audit_body_sample(
                    page, store_key, reviews, limit=len(seen),
                    deadline=time.monotonic() + COUNT_BODY_SECONDS,
                )
                evidence = count_body_evidence(report["body_sample"], len(seen))
                report["count_body_evidence"] = evidence
                if blocked(page):
                    report["status"] = "ACCESS_RESTRICTED_STOPPED"
                    return report
                if (evidence in {"COUNT_BODY_CONTEXT_LOST", "COUNT_BODY_INCOMPLETE"}
                        or not same_place(page.url, store_key) or not selected(reviews)):
                    report["status"] = "COUNT_BODY_AUDIT_INCOMPLETE"
                    return report
                after_fields, after_records = audit_loaded_fields(page, len(seen), include_records=True)
                report["post_body_field_audit"] = after_fields
                report["post_body_same_card_set"] = verified_record_set(after_records, seen)
                del after_records
                if (not report["post_body_same_card_set"] or after_fields["duplicate_cards"]
                        or after_fields["status"] != "REQUIRED_FIELDS_PRESENT"):
                    report["status"] = "COUNT_BODY_AUDIT_CARD_OR_FIELD_GAPS"
                    return report
                if not count_db_audit:
                    report["status"] = ("LOCAL_COUNT_BODY_CONTROLS_CHECKED"
                                        if evidence == "COUNT_BODY_CONTROLS_CHECKED"
                                        else ("LOCAL_COUNT_BODY_CONTROL_GAPS" if evidence == "COUNT_BODY_CONTROL_GAPS"
                                              else "LOCAL_COUNT_BODY_EVIDENCE_LIMITED"))
                    return report
            report["phase"] = "count_matched_db_audit"
            report["db_sample"] = compare_db_sample(page, store_key, len(seen), expected_seen=seen)
            report["status"] = report["db_sample"]["status"]
            if count_body_audit and report["status"] == "LOCAL_COUNT_DB_COMPARED":
                report["status"] = ("LOCAL_COUNT_BODY_DB_COMPARED"
                                    if report["count_body_evidence"] == "COUNT_BODY_CONTROLS_CHECKED"
                                    else "LOCAL_COUNT_BODY_DB_EVIDENCE_LIMITED")
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
        if "elapsed_scroll_seconds" not in report:
            report["elapsed_scroll_seconds"] = (round(time.monotonic() - scroll_started, 1)
                                                if scroll_started is not None else None)
        if page is not None and not page.is_closed():
            try:
                report["ui_summary"] = page_summary(page)
            except Exception:
                pass


def self_test():
    assert same_place(PLACE_URL)
    order_fixture = [{"source_id":"first"},{"source_id":"second"}]
    order_hashes = [hashlib.sha256(r["source_id"].encode()).hexdigest() for r in order_fixture]
    assert verified_record_order(order_fixture, order_hashes)
    assert not verified_record_order(order_fixture[::-1], order_hashes)
    assert not verified_record_order(order_fixture+[order_fixture[0]], order_hashes)
    assert displayed_age_evidence(["a week ago","4 months ago"])["displayed_order_consistent"]
    assert displayed_age_evidence(["4 months ago","a week ago"])["clear_inversions"] == 1
    assert not displayed_age_evidence(["a week ago","a week ago"])["displayed_order_consistent"]
    assert not displayed_age_evidence(["a week ago",None])["displayed_order_consistent"]
    assert relative_age_interval("Edited 2 days ago") is not None
    assert relative_age_interval("unknown") is None
    fixture_options = [dict(label=x,role="menuitemradio",state={"aria-checked":"false","aria-selected":None,"aria-pressed":None,"aria-current":None},native_checked=[],indicators=[]) for x in ("most relevant","newest","highest rating","lowest rating")]
    assert all_sort_options_unmarked(fixture_options)
    fixture_options[0]["state"]["aria-checked"]="true"
    assert not all_sort_options_unmarked(fixture_options)
    head = [str(i) for i in range(30)]
    assert ordered_extension(head, head+["extra"])
    assert not ordered_extension(head, list(reversed(head)))
    assert compare_newest_heads([head,head])["status"] == "NEWEST_HEAD_MATCHED"
    assert compare_newest_heads([head,list(reversed(head))])["status"] == "NEWEST_HEAD_CHANGED"
    assert compare_newest_heads([head])["status"] == "NEWEST_HEAD_COMPARISON_INCOMPLETE"
    assert stall_evidence_status(None,0) == "PANE_UNVERIFIED"
    assert stall_evidence_status({"at_bottom":True},1) == "VISIBLE_BUSY_INDICATOR"
    assert stall_evidence_status({"at_bottom":True},0) == "PANE_BOTTOM_NO_VISIBLE_BUSY"
    assert stall_evidence_status({"at_bottom":False},0) == "PANE_NOT_AT_BOTTOM"
    waits = []
    samples = iter([(None, {"visible_expected_cards":0}), (None, {"visible_expected_cards":1})])
    status, ticks, evidence = initial_card_poll(lambda: next(samples), lambda: waits.append(1), 2)
    assert status == "INITIAL_REVIEW_CARDS_VISIBLE" and ticks == 1 and len(waits) == 1
    waits.clear()
    status, ticks, _ = initial_card_poll(lambda: (None, {"visible_expected_cards":0}), lambda: waits.append(1), 2)
    assert status == "INITIAL_REVIEW_CARDS_TIMEOUT" and ticks == 2 and len(waits) == 2
    for failure in ("ACCESS_RESTRICTED_STOPPED", "REVIEW_CONTEXT_LOST"):
        status, ticks, _ = initial_card_poll(lambda: (failure, {}), lambda: None, 2)
        assert status == failure and ticks == 0
    reveal_calls = []
    status, ticks, _ = initial_card_poll(lambda: (None, {"visible_expected_cards":0}),
                                         lambda: None, 45, reveal=lambda: reveal_calls.append(1))
    assert status == "INITIAL_REVIEW_CARDS_TIMEOUT" and ticks == 45 and len(reveal_calls) == 6
    reveal_calls.clear()
    state = {"ready":False}
    def fixture_reveal():
        reveal_calls.append(1)
        state["ready"] = True
    status, ticks, _ = initial_card_poll(lambda: (None, {"visible_expected_cards":int(state["ready"])}),
                                         lambda: None, 45, reveal=fixture_reveal)
    assert status == "INITIAL_REVIEW_CARDS_VISIBLE" and ticks == 5 and len(reveal_calls) == 1
    a = {"status":"UI_DISPLAYED","displayed_total":167,"candidate_counts":[167]}
    assert stable_overview_total(a, a) == 167
    assert scaled_count_budget(167, 240, 600, True) == (240, 600)
    assert scaled_count_budget(6332, 240, 600, False) == (240, 600)
    assert scaled_count_budget(6332, 240, 600, True) == (3206, 10800)
    assert scaled_count_budget(10000, 240, 600, True) == (5000, 10800)
    assert scaled_count_budget(167, 500, 1000, True) == (500, 1000)
    assert stable_overview_total(a, dict(a, displayed_total=168, candidate_counts=[168])) is None
    assert stable_overview_total(a, dict(a, status="AMBIGUOUS")) is None
    assert stable_overview_total(a, None) is None
    assert stable_overview_total(dict(a, displayed_total=0, candidate_counts=[0]), dict(a, displayed_total=0, candidate_counts=[0])) is None
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
    assert not same_place("https://www.google.com/maps/place/other/!1s0x123:0x484a32408c147d14")
    assert not same_place("https://www.google.com/maps/place/other/!1s0x123:0x484a32408c147d140")
    assert not same_place("https://www.google.com/maps/place/other/" + PLACE_TOKEN)
    assert not same_place(PLACE_URL.replace("www.google.com", "user@www.google.com"))
    assert not same_place(PLACE_URL.replace("www.google.com", "www.google.com:443"))
    assert same_place(maps_language_url(PLACE_URL, "en"))
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
    assert count_budget_status(5, 10, 10, 60) is None
    assert count_budget_status(10, 10, 10, 60) == "ROUND_LIMIT"
    assert count_budget_status(5, 60, 10, 60) == "TIME_BUDGET_REACHED"
    assert coverage_status(6332, 6332) == "EXPECTED_COUNT_MATCHED"
    assert coverage_status(6331, 6332) == "EXPECTED_COUNT_NOT_REACHED"
    expected = {hashlib.sha256(x.encode()).digest() for x in ("a", "b")}
    assert verified_record_set([{"source_id": "a"}, {"source_id": "b"}], expected)
    assert not verified_record_set([{"source_id": "a"}, {"source_id": "c"}], expected)
    assert not verified_record_set([{"source_id": "a"}, {"source_id": "a"}], expected)
    assert not verified_record_set([{"source_id": None}], expected)
    body = dict(context_lost=False, identity_mismatch=0, time_budget_reached=False,
                processed_cards=2, click_errors=0, previously_present_body_lost=0,
                more_control_resolved=1, more_candidates=1, original_confirmed=0,
                original_candidates=0, more_closed_without_growth=0, more_details_only=0,
                original_text_changed=0, body_missing_after=0, primary_fingerprint_unavailable=0)
    assert count_body_evidence(body, 2) == "COUNT_BODY_CONTROLS_CHECKED"
    assert count_body_evidence(dict(body, body_missing_after=1), 2) == "COUNT_BODY_EVIDENCE_LIMITED"
    assert count_body_evidence(dict(body, processed_cards=1), 2) == "COUNT_BODY_INCOMPLETE"
    assert count_body_evidence(dict(body, click_errors=1), 2) == "COUNT_BODY_CONTROL_GAPS"
    assert fresh_depth_status(8, 8) == "REVIEW_DEPTH_UNVERIFIED"
    assert fresh_depth_status(5, 6) == "REVIEW_DEPTH_VERIFIED"
    assert fresh_depth_status(8, 9, True) == "ACCESS_RESTRICTED_STOPPED"
    assert local_date_value("수정: 어제", base, FakeProduction) == ("2026-11-23", "estimated")
    assert local_date_value("일주일 전", base, FakeProduction) == ("2026-11-17", "estimated")
    assert exact_place_pair(PLACE_URL) == "0x30e29df2eeea54a1:0x484a32408c147d14"
    assert exact_place_pair(STORE_CONFIG["taiwan"]["url"]) == "0x3442ab0779763169:0x584a72379db46e23"
    assert exact_place_pair("https://example.com/maps/place/a/!1s0x1:0x2") is None
    assert exact_place_pair("https://www.google.com/maps/place/a/!1s0x1:0x2!1s0x3:0x4") is None
    assert normalize_history_row({"text": "", "review_text": "fixture"})["text"] == "fixture"
    assert normalize_history_row({"date": "2 days ago", "relative_date": None})["date"] == "2 days ago"
    try:
        normalize_history_row({"text": "fixture A", "review_text": "fixture B"})
        raise AssertionError("conflict must be rejected")
    except ValueError as exc:
        assert str(exc) == "AUDIT_HISTORY_FIELD_CONFLICT"
    class MatchFixtureProduction:
        @staticmethod
        def normalize_spaces(value):
            return " ".join(value.split())
        @staticmethod
        def normalized_review_text_for_match(value):
            return re.sub(r"[^\w]+", "", " ".join((value or "").split()).casefold())
        @staticmethod
        def canonical_review_hash(row):
            return "fixture-key"
    history = [{"author":"A", "rating":5, "text":"Old English text", "review_key":"fixture-key"},
               {"author":"B", "rating":4, "text":"Same!", "review_key":"fixture-key"}]
    live = [{"author":"A", "rating":5, "body":"다른 언어", "body_scope":"PRIMARY", "legacy_body_probe":"Old English text"},
            {"author":"B", "rating":4, "body":"Same!", "body_scope":"PRIMARY", "legacy_body_probe":"Same!"},
            {"author":"A", "rating":5, "body":"", "body_scope":"NOT_DETECTED", "legacy_body_probe":"Old English text"},
            {"author":"C", "rating":3, "body":"New", "body_scope":"PRIMARY"}]
    evidence = match_evidence(live, history, MatchFixtureProduction)
    assert evidence["counts"]["observed"] == 4
    assert evidence["counts"]["one_to_one_author_rating_candidate"] == 1
    assert evidence["counts"]["author_rating_exact_body"] == 1
    assert evidence["counts"]["author_rating_different_body"] == 1
    assert evidence["counts"]["author_rating_body_unverified"] == 1
    assert evidence["counts"]["no_author_match"] == 1
    assert evidence["legacy_extractor_shadow_counts"]["broad_exact_author_rating_body"] == 3
    assert evidence["legacy_extractor_shadow_counts"]["broad_match_not_same_as_scoped"] == 2
    assert evidence["history_canonical_key_matches"] == 2
    assert evidence["write_approved"] is False and evidence["identity_confirmed_by_metadata"] is False
    assert maps_language_url(PLACE_URL, "profile") == PLACE_URL
    english_url = maps_language_url(PLACE_URL, "en")
    assert exact_place_pair(english_url) == exact_place_pair(PLACE_URL)
    assert parse_qsl(urlsplit(english_url).query).count(("hl", "en")) == 1
    assert parse_qsl(urlsplit(maps_language_url(english_url + "&hl=ko", "en")).query).count(("hl", "en")) == 1
    assert not any(k == "hl" and v != "en" for k,v in parse_qsl(urlsplit(maps_language_url(english_url + "&hl=ko", "en")).query))
    class IdentityFixtureProduction(MatchFixtureProduction):
        @staticmethod
        def hash_google_source_review_id(store_id, source_id):
            return hashlib.sha256((store_id + ":" + source_id).encode()).hexdigest() if source_id else None
    old = [{"id":"1","author":"A","rating":5,"text":"Exact"},
           {"id":"2","author":"B","rating":4,"text":"Shared"}]
    current = [{"source_id":"a","author":"A","rating":5,"body":"Exact","body_scope":"PRIMARY"},
               {"source_id":"b","author":"B","rating":4,"body":"Shared","body_scope":"PRIMARY"},
               {"source_id":"c","author":"B","rating":4,"body":"Shared","body_scope":"PRIMARY"},
               {"source_id":"d","author":"D","rating":5,"body":"","body_scope":"NOT_DETECTED"},
               {"source_id":"e","author":"E","rating":5,"body":"New","body_scope":"PRIMARY"}]
    p = source_identity_preview(current, old, "store", IdentityFixtureProduction)
    assert p["balanced"] and p["classified"] == 5
    assert p["counts"]["one_to_one_exact_proposal"] == 1
    assert p["counts"]["shared_target_held"] == 2
    assert p["counts"]["body_unverified"] == 1
    assert p["counts"]["no_exact_target"] == 1
    assert p["links_persisted"] == 0 and p["write_approved"] is False
    p = source_identity_preview(current + [current[0]], old, "store", IdentityFixtureProduction)
    assert p["counts"]["invalid_or_duplicate_source"] == 2
    assert p["balanced"] and p["counts"].get("one_to_one_exact_proposal", 0) == 0
    from review_source_identity import self_test as source_replay_self_test
    source_replay_self_test()
    print("SELF_TEST_PASS: 102 checks plus source replay suite")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--newest-head-audit", action="store_true", help="Two independent read-only 30-ID head observations, no ID output.")
    parser.add_argument("--newest-head-db-audit", action="store_true", help="With newest-head-audit, GET-only legacy comparison after two matching heads.")
    parser.add_argument("--maps-language", choices=("profile", "en"), default="profile", help="Request English Maps display for a diagnostic; no account setting change.")
    parser.add_argument("--db-read-preflight", action="store_true", help="Verify DB read access and history without opening Chrome.")
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
    parser.add_argument("--db-sample", action="store_true",
                        help="Compare initial cards with caller-visible database rows; GET only.")
    parser.add_argument("--count-round-limit", type=int, default=240,
                        help="Explicit maximum scroll rounds for a count check.")
    parser.add_argument("--count-second-limit", type=int, default=600,
                        help="Explicit elapsed scroll budget in seconds; no automatic retry.")
    parser.add_argument("--count-db-audit", action="store_true",
                        help="GET-only comparison of the count-matched card set; bounded pilot, no write approval.")
    parser.add_argument("--count-body-audit", action="store_true",
                        help="Bounded body-control audit after count match; DB comparison is optional.")
    args = parser.parse_args()
    if args.newest_head_db_audit:
        if not args.newest_head_audit:
            parser.error("--newest-head-db-audit requires --newest-head-audit")
        try:
            read_only_db_config()
        except Exception:
            print("LOCAL_DB_AUDIT_CONFIG_UNAVAILABLE")
            return 2
    if args.newest_head_audit and (args.maps_language != "en" or args.auto_total or args.expected_total is not None or args.audit_fields or args.field_sample or args.body_sample or args.adapter_sample or args.db_sample or args.count_db_audit or args.count_body_audit or args.db_read_preflight or args.self_test):
        parser.error("--newest-head-audit is a standalone English diagnostic")
    if args.maps_language == "en" and (args.db_read_preflight or args.self_test):
        parser.error("--maps-language en is for direct place diagnostics only")
    if args.db_read_preflight:
        if args.self_test or args.count_body_audit or args.count_db_audit or args.expected_total is not None or args.auto_total or args.field_sample or args.body_sample or args.adapter_sample or args.db_sample or args.audit_fields:
            parser.error("--db-read-preflight is standalone")
        try:
            result = db_read_preflight(args.store)
        except Exception as exc:
            print("LOCAL_DB_READ_PREFLIGHT: " + json.dumps({"status": "DB_READ_PREFLIGHT_FAILED", "error_type": type(exc).__name__, "reason": str(exc) if type(exc) is ValueError and str(exc).startswith("AUDIT_") else None, "database_writes": False}))
            return 2
        print("LOCAL_DB_READ_PREFLIGHT: " + json.dumps(result, ensure_ascii=False))
        return 0
    if args.count_body_audit:
        if (args.expected_total is None or not 1 <= args.expected_total <= MAX_COUNT_BODY_AUDIT
                or args.auto_total or args.field_sample or args.body_sample or args.adapter_sample or args.db_sample):
            parser.error("--count-body-audit requires explicit total <= 250 and no sample mode")
        args.audit_fields = True
    if args.count_db_audit:
        if (args.expected_total is None or not 1 <= args.expected_total <= MAX_COUNT_DB_AUDIT
                or args.auto_total or args.field_sample or args.body_sample or args.adapter_sample or args.db_sample):
            parser.error("--count-db-audit requires explicit --expected-total between 1 and 1000")
        try:
            read_only_db_config()
        except Exception:
            print("LOCAL_DB_AUDIT_CONFIG_UNAVAILABLE")
            return 2
        args.audit_fields = True
    if not 1 <= args.count_round_limit <= MAX_COUNT_ROUNDS or not 1 <= args.count_second_limit <= MAX_COUNT_SECONDS:
        parser.error("count budget outside diagnostic limits")
    if args.db_sample and (args.adapter_sample or args.body_sample or args.field_sample or args.audit_fields or args.auto_total or args.expected_total is not None):
        parser.error("--db-sample is a standalone diagnostic")
    if args.db_sample:
        try:
            read_only_db_config()
        except Exception:
            print("LOCAL_DB_AUDIT_CONFIG_UNAVAILABLE")
            return 2
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
    if args.expected_total is not None and not 1 <= args.expected_total <= MAX_EXPECTED_COUNT:
        parser.error("--expected-total must be between 1 and 10000")
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
    newest_heads = [] if args.newest_head_audit else None
    # No export or import of cookies, no synthetic browser identity. Each
    # trial opens and closes the existing dedicated local Chrome normally.
    count_mode = args.auto_total or args.expected_total is not None
    target_runs = 1 if count_mode or args.field_sample or args.body_sample or args.adapter_sample or args.db_sample else args.runs
    success_status = "FIELD_SAMPLE_VERIFIED" if args.field_sample else ("EXPECTED_COUNT_MATCHED" if count_mode else "REVIEW_DEPTH_VERIFIED")
    if args.body_sample:
        success_status = "BODY_SAMPLE_CONTROLS_VERIFIED"
    if args.adapter_sample:
        success_status = "LOCAL_ADAPTER_SAMPLE_PASSED"
    if args.db_sample:
        success_status = "LOCAL_DB_SAMPLE_COMPARED"
    if args.count_body_audit:
        success_status = "LOCAL_COUNT_BODY_CONTROLS_CHECKED"
    if args.count_db_audit:
        success_status = "LOCAL_COUNT_BODY_DB_COMPARED" if args.count_body_audit else "LOCAL_COUNT_DB_COMPARED"
    if args.newest_head_audit:
        target_runs = 2
        success_status = "NEWEST_HEAD_SAMPLE_VERIFIED"
    for attempt in range(1, target_runs + 1):
        context = None
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel="chrome", headless=False,
                    args=["--profile-directory=Default"],
                    **({"locale": "en-US"} if args.maps_language == "en" else {}),
                )
                try:
                    report = run_once(context, args.expected_total, args.store, args.auto_total, args.scroll_mode, args.audit_fields, args.field_sample, args.body_sample, args.adapter_sample, args.db_sample, args.count_round_limit, args.count_second_limit, args.count_db_audit, args.count_body_audit, maps_language=args.maps_language, newest_heads=newest_heads, newest_db_audit=args.newest_head_db_audit)
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
    if args.db_sample:
        final_status = "LOCAL_DB_SAMPLE_COMPARED" if passed else "LOCAL_DB_SAMPLE_GAPS"
    if args.count_body_audit:
        final_status = success_status if passed else reports[-1].get("status", "LOCAL_COUNT_BODY_GAPS")
    elif args.count_db_audit:
        final_status = success_status if passed else "LOCAL_COUNT_DB_GAPS"
    if args.newest_head_audit:
        comparison = compare_newest_heads(newest_heads)
        # Keep observation evidence separate from later DB/body validation.
        # A subsequent hold does not undo the already recorded head samples.
        head_matched = (comparison["status"] == "NEWEST_HEAD_MATCHED"
                        and len(reports)==2
                        and all(r.get("newest_head_sample_verified") is True
                                and r.get("newest_date_evidence",{}).get("displayed_order_consistent") is True
                                for r in reports))
        passed = passed and head_matched
        explicit = head_matched and all(r.get("newest_selection_explicit") is True for r in reports)
        comparison["head_sample_matched"] = head_matched
        comparison["selection_explicit_verified"] = explicit
        comparison["displayed_order_consistent"] = head_matched
        comparison["publication_order_verified"] = False
        comparison["stop_authorized"] = False
        comparison["newest_db_audit_requested"] = args.newest_head_db_audit
        if args.newest_head_db_audit:
            db_preview = reports[-1].get("newest_db_preview") if reports else None
            comparison["newest_db_preview_status"] = db_preview.get("status") if db_preview else "NOT_COMPARED"
            comparison["baseline_committed"] = False
            comparison["db_comparison_completed"] = bool(db_preview and db_preview.get("actual_database_compared") is True)
            comparison["classification_balanced"] = bool(db_preview and db_preview.get("classification_balanced") is True)
            comparison["strict_adapter_preflight_passed"] = bool(db_preview and db_preview.get("strict_adapter_preflight_passed") is True)
            comparison["body_audit_status"] = reports[-1].get("newest_body_audit_status","NOT_RUN") if reports else "NOT_RUN"
            if not passed or comparison["newest_db_preview_status"]!="LOCAL_COUNT_DB_COMPARED":
                passed = False
                comparison["status"] = "NEWEST_DB_PREVIEW_HELD"
        if passed and not explicit:
            comparison["status"] = "NEWEST_HEAD_MATCHED_BEHAVIOR_ONLY"
        print("LOCAL_NEWEST_HEAD_FINAL: " + json.dumps(dict(comparison, attempts=len(reports), database_writes=False, full_coverage_verified=False)), flush=True)
        return 0 if passed else 2
    print("LOCAL_REVIEW_FINAL: " + json.dumps({
        "status": final_status,
        "attempts": len(reports), "database_writes": False,
        "store": STORE_CONFIG[args.store]["name"],
        "expected_total_user_observed": reports[-1].get("expected_total_user_observed") if reports else args.expected_total,
        "observed_unique": reports[-1].get("observed_unique", 0) if reports else 0,
        "initial_unique": reports[-1].get("initial_unique", 0) if reports else 0,
        "additional_unique": reports[-1].get("additional_unique", 0) if reports else 0,
        "scroll_mode": args.scroll_mode,
        "maps_language_requested": args.maps_language,
        "maps_ui_language": reports[-1].get("maps_ui_language", "UNVERIFIED") if reports else "UNVERIFIED",
        "scroll_rounds": reports[-1].get("scroll_rounds", 0) if reports else 0,
        "stop_reason": reports[-1].get("stop_reason") if reports else None,
        "count_gap": reports[-1].get("count_gap") if reports else None,
        "elapsed_scroll_seconds": reports[-1].get("elapsed_scroll_seconds") if reports else None,
        "field_audit": reports[-1].get("field_audit") if reports else None,
        "body_sample": reports[-1].get("body_sample") if reports else None,
        "count_body_evidence": reports[-1].get("count_body_evidence") if reports else None,
        "post_body_field_audit": reports[-1].get("post_body_field_audit") if reports else None,
        "post_body_same_card_set": reports[-1].get("post_body_same_card_set") if reports else None,
        "integration_sample": reports[-1].get("integration_sample") if reports else None,
        "db_sample": reports[-1].get("db_sample") if reports else None,
        "full_coverage_verified": False,
    }), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
