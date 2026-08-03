import os
import json
import re
import hashlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
STATUS_ONLY = os.environ.get("STATUS_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
REPAIR_ONLY = os.environ.get("REPAIR_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}

MAX_SCROLL_ROUNDS = 8
STOP_STALLED_ROUNDS = 2
MIN_REVIEWS_TARGET = 50

# Recent-only mode settings
# If a store already has saved reviews, the crawler checks only the latest area.
RECENT_ONLY_MAX_REVIEWS = 20
RECENT_ONLY_EXISTING_HIT_LIMIT = 3
RECENT_ONLY_MIN_CHECKED = 10
RECENT_ONLY_MAX_ROUNDS = 3

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return datetime.now(KST)


def estimate_review_date(relative_date, base_date=None):
    """Convert Google Maps relative time text to an estimated calendar date."""
    if base_date is None:
        base_date = now_kst().date()

    text = normalize_spaces(relative_date).lower()

    if not text or text in {"unknown", "recent"}:
        return base_date.strftime("%Y-%m-%d")

    # Words used when Google omits a number, e.g. "a day ago".
    text = re.sub(r"\b(?:a|an|one|een|satu)\b", "1", text)

    unit_patterns = [
        (r"(\d+)\s*(?:second|seconds|초|detik|seconde|seconden)", 0),
        (r"(\d+)\s*(?:minute|minutes|분|menit|minuut|minuten)", 0),
        (r"(\d+)\s*(?:hour|hours|시간|jam|uur)", 0),
        (r"(\d+)\s*(?:day|days|일|hari|dag|dagen)", 1),
        (r"(\d+)\s*(?:week|weeks|주|minggu|weken)", 7),
        (r"(\d+)\s*(?:month|months|개월|달|bulan|maand|maanden)", 30),
        (r"(\d+)\s*(?:year|years|년|tahun|jaar|jaren)", 365),
    ]

    for pattern, days_per_unit in unit_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            amount = int(match.group(1))
            estimated = base_date - timedelta(days=amount * days_per_unit)
            return estimated.strftime("%Y-%m-%d")

    # Unrecognized relative values remain usable, but are marked as estimated today.
    return base_date.strftime("%Y-%m-%d")


def build_url_candidates(url):
    base = url.strip()
    urls = [base]

    reviews_url = base.split("?")[0].rstrip("/") + "/reviews/"
    if reviews_url not in urls:
        urls.append(reviews_url)

    return urls


def normalize_spaces(text):
    return re.sub(r"\s+", " ", text or "").strip()


def safe_inner_text(locator, default=""):
    try:
        if locator.count() > 0:
            return locator.first.inner_text().strip()
    except:
        pass
    return default


def safe_attr(locator, attr, default=""):
    try:
        if locator.count() > 0:
            value = locator.first.get_attribute(attr)
            return value.strip() if value else default
    except:
        pass
    return default


def parse_rating(label):
    if not label:
        return 5

    match = re.search(r"([1-5])", label)
    return int(match.group(1)) if match else 5


def click_cookie_buttons(page):
    patterns = [
        r"Accept all",
        r"Accept",
        r"I agree",
        r"Agree",
        r"동의",
        r"모두 수락",
        r"Alles accepteren",
        r"Akkoord",
    ]

    for pattern in patterns:
        try:
            btn = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                print("✅ 쿠키/동의 버튼 클릭 완료")
                page.wait_for_timeout(1500)
                return
        except:
            pass


def has_review_dom(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        ".MyEned",
        ".wiI7pd",
        "div[role='feed']",
    ]

    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except:
            pass

    return False


def is_valid_google_maps_place_page(page):
    """Return True only when a real Google Maps place detail page is visible.

    A valid place may legitimately have zero reviews. Search result pages, consent
    screens, CAPTCHA pages, and broken URLs must not be treated as successful stores.
    """
    try:
        current_url = (page.url or "").lower()
    except Exception:
        current_url = ""

    if "google." not in current_url or "/maps" not in current_url:
        return False

    # Strong place-detail signals used by Google Maps desktop layouts.
    strong_selectors = [
        "h1.DUwDvf",
        "button[data-item-id^='address']",
        "button[data-item-id^='phone']",
        "button[data-item-id^='authority']",
        "button[data-item-id='oh']",
    ]

    for selector in strong_selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            pass

    # Fallback: a place URL plus a visible heading and at least one place action.
    if "/maps/place/" in current_url:
        try:
            heading = page.locator("h1").first
            heading_text = normalize_spaces(safe_inner_text(heading, ""))
            action_count = page.locator(
                "button[aria-label*='Directions'], "
                "button[aria-label*='Save'], "
                "button[aria-label*='Share'], "
                "button[aria-label*='경로'], "
                "button[aria-label*='저장'], "
                "button[aria-label*='공유']"
            ).count()
            if heading_text and action_count > 0:
                return True
        except Exception:
            pass

    return False


def open_reviews_panel(page):
    print("🔘 리뷰 패널 열기 시도 중...")

    click_targets = [
        ("tab reviews", lambda: page.get_by_role("tab", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen|Ulasan", re.I)).first),
        ("button reviews", lambda: page.get_by_role("button", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen|Ulasan", re.I)).first),
        ("aria reviews", lambda: page.locator("button[aria-label*='Reviews'], button[aria-label*='reviews'], button[aria-label*='리뷰'], button[aria-label*='Recensies'], button[aria-label*='recensies'], button[aria-label*='Beoordelingen'], button[aria-label*='beoordelingen'], button[aria-label*='Ulasan'], button[aria-label*='ulasan']").first),
        ("jsaction moreReviews", lambda: page.locator("button[jsaction*='pane.rating.moreReviews']").first),
        ("text reviews", lambda: page.locator("text=/Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i").first),
    ]

    for name, get_locator in click_targets:
        try:
            locator = get_locator()
            if locator.count() > 0:
                print(f"🔘 클릭 후보 발견: {name}")
                locator.click(timeout=5000, force=True)
                page.wait_for_timeout(6000)
                print(f"✅ 클릭 실행 완료: {name}")

                if has_review_dom(page):
                    print("✅ 클릭 후 리뷰 DOM 감지")
                    return True
        except Exception as e:
            print(f"⚠️ 클릭 실패: {name} / {e}")

    print("⚠️ 리뷰 패널 클릭으로 열기 실패")
    return False


def wait_for_reviews(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        ".MyEned",
        ".wiI7pd",
        "div[role='feed']",
    ]

    for attempt in range(8):
        for selector in selectors:
            try:
                count = page.locator(selector).count()
                if count > 0:
                    print(f"✅ 리뷰 영역 감지: {selector} / {count}개")
                    return True
            except:
                pass

        print(f"⏳ 리뷰 패널 대기 중... {attempt + 1}/8")
        page.wait_for_timeout(3000)

    return False


def set_reviews_sort_to_newest(page):
    print("🆕 리뷰 정렬을 최신순으로 변경 시도 중...")

    sort_button_patterns = [
        r"Sort",
        r"정렬",
        r"Sorteer",
        r"Sorteren",
        r"Urutkan",
    ]

    newest_patterns = [
        r"Newest",
        r"Newest first",
        r"Most recent",
        r"Latest",
        r"최신",
        r"최신순",
        r"Nieuwste",
        r"Meest recente",
        r"Terbaru",
        r"Paling baru",
    ]

    try:
        sort_clicked = False

        for pattern in sort_button_patterns:
            try:
                btn = page.get_by_role("button", name=re.compile(pattern, re.I)).first

                if btn.count() > 0:
                    btn.click(timeout=4000, force=True)
                    page.wait_for_timeout(2000)
                    print("✅ 정렬 버튼 클릭 성공")
                    sort_clicked = True
                    break
            except:
                pass

        if not sort_clicked:
            print("⚠️ 정렬 버튼 발견 실패")
            return False

        newest_clicked = False

        for pattern in newest_patterns:
            try:
                option = page.get_by_role("menuitemradio", name=re.compile(pattern, re.I)).first

                if option.count() > 0:
                    option.click(timeout=4000, force=True)
                    page.wait_for_timeout(4000)
                    print("✅ 최신순 정렬 적용 성공")
                    newest_clicked = True
                    break
            except:
                pass

        if not newest_clicked:
            for pattern in newest_patterns:
                try:
                    option = page.get_by_text(re.compile(pattern, re.I)).first

                    if option.count() > 0:
                        option.click(timeout=4000, force=True)
                        page.wait_for_timeout(4000)
                        print("✅ 최신순 정렬 적용 성공")
                        newest_clicked = True
                        break
                except:
                    pass

        if not newest_clicked:
            print("⚠️ 최신순 옵션 클릭 실패")
            return False

        return True

    except Exception as e:
        print(f"⚠️ 최신순 정렬 설정 실패: {e}")
        return False


def click_more_buttons(page):
    patterns = [
        r"More",
        r"Read more",
        r"자세히 보기",
        r"더보기",
        r"Meer",
        r"Meer weergeven",
        r"Volledige review",
        r"Lainnya",
        r"Selengkapnya",
    ]

    for pattern in patterns:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            count = min(buttons.count(), 20)

            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=700, force=True)
                    page.wait_for_timeout(80)
                except:
                    pass
        except:
            pass


def click_original_review_buttons(page):
    patterns = [
        r"See original",
        r"Show original",
        r"Original",
        r"원문 보기",
        r"원본 보기",
        r"Bekijk origineel",
        r"Origineel bekijken",
        r"Oorspronkelijke",
        r"Lihat asli",
        r"Tampilkan asli",
    ]

    for pattern in patterns:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            count = min(buttons.count(), 30)

            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=700, force=True)
                    page.wait_for_timeout(80)
                except:
                    pass
        except:
            pass


def get_review_cards(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        "div[data-review-id]",
    ]

    for selector in selectors:
        try:
            cards = page.locator(selector)
            if cards.count() > 0:
                return cards, selector
        except:
            pass

    return page.locator(".jftiEf"), ".jftiEf"


def get_review_text(card):
    for selector in [".wiI7pd", ".MyEned"]:
        text = normalize_spaces(safe_inner_text(card.locator(selector), ""))
        if text:
            return text

    return ""


def get_review_date(card):
    value = normalize_spaces(safe_inner_text(card.locator(".rsqaof"), ""))
    if value:
        return value

    try:
        all_text = card.inner_text(timeout=1000)

        patterns = [
            r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b",
            r"\b\d+\s*(?:초|분|시간|일|주|개월|년)\s*전\b",
            r"\b\d+\s+(?:seconden|minuten|uur|dagen|weken|maanden|jaar)\s+geleden\b",
            r"\b\d+\s+(?:detik|menit|jam|hari|minggu|bulan|tahun)\s+yang\s+lalu\b",
            r"\b(?:a|an)\s+(?:day|week|month|year)\s+ago\b",
            r"\b(?:een)\s+(?:dag|week|maand|jaar)\s+geleden\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, all_text, re.I)
            if match:
                return normalize_spaces(match.group(0))
    except:
        pass

    return "Unknown"


def get_review_author(card):
    author = normalize_spaces(safe_inner_text(card.locator(".d4r55"), ""))
    return author if author else "Anonymous"


def get_review_rating(card):
    rating_label = safe_attr(
        card.locator(
            "span[aria-label*='star'], span[aria-label*='Star'], span[aria-label*='stars'], span[aria-label*='Stars'], span[aria-label*='별'], span[aria-label*='ster'], span[aria-label*='Ster'], span[aria-label*='bintang'], span[aria-label*='Bintang']"
        ),
        "aria-label",
        "",
    )

    return parse_rating(rating_label)


def get_scroll_target(page):
    candidates = [
        "div[role='feed']",
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
        "div.m6QErb[tabindex='-1']",
    ]

    for selector in candidates:
        try:
            target = page.locator(selector).first
            if target.count() > 0:
                return target
        except:
            pass

    return None


def scroll_reviews(page):
    target = get_scroll_target(page)

    try:
        if target:
            target.hover(timeout=2000)
        else:
            page.mouse.move(500, 500)
    except:
        page.mouse.move(500, 500)

    page.mouse.wheel(0, 8000)
    page.wait_for_timeout(900)
    page.keyboard.press("PageDown")
    page.wait_for_timeout(1400)


def require_supabase_config():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 환경변수가 없습니다."
        )


def supabase_request(method, table, *, query=None, body=None, prefer=None):
    require_supabase_config()

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if query:
        url += "?" + urlencode(query, safe=",.*()")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }

    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if prefer:
        headers["Prefer"] = prefer

    request = Request(url, data=payload, headers=headers, method=method)

    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Supabase 요청 실패 ({exc.code} {exc.reason}): {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase 연결 실패: {exc.reason}") from exc



def load_stores_from_supabase():
    """Load active crawler stores from Supabase as the single source of truth."""
    rows = supabase_request(
        "GET",
        "stores",
        query={
            "select": "id,brand,country,sv,store_name,google_maps_url,is_active,display_order",
            "is_active": "eq.true",
            "order": "display_order.asc,store_name.asc",
            "limit": "1000",
        },
    ) or []

    stores = []
    for row in rows:
        store_name = normalize_spaces(row.get("store_name", ""))
        google_maps_url = normalize_spaces(row.get("google_maps_url", ""))
        country = normalize_spaces(row.get("country", ""))
        sv = normalize_spaces(row.get("sv", ""))
        brand = normalize_spaces(row.get("brand", ""))

        stores.append({
            "id": row.get("id"),
            "brand": brand,
            "store_name": store_name,
            "sv": sv,
            "country": country,
            "city": "",
            "url": google_maps_url,
            "display_order": row.get("display_order"),
        })

    if not stores:
        raise RuntimeError(
            "Supabase stores 테이블에서 is_active=true 매장을 찾지 못했습니다."
        )

    print(f"🏪 Supabase 활성 매장 로드: {len(stores)}개")
    return stores



def normalize_store_lookup_key(value):
    return normalize_spaces(value).casefold()


def load_store_id_map():
    """Load Supabase stores.id keyed by normalized stores.store_name."""
    rows = supabase_request(
        "GET",
        "stores",
        query={
            "select": "id,store_name",
            "limit": "1000",
        },
    ) or []

    store_id_map = {}
    for row in rows:
        store_id = row.get("id")
        store_name = normalize_spaces(row.get("store_name", ""))
        if store_id and store_name:
            store_id_map[normalize_store_lookup_key(store_name)] = store_id

    if not store_id_map:
        raise RuntimeError(
            'Supabase stores 테이블에서 "id, store_name" 데이터를 찾지 못했습니다.'
        )

    print(f"🏪 Supabase 매장 ID 로드: {len(store_id_map)}개")
    return store_id_map


def load_existing_reviews(page_size=1000):
    """Load every Supabase review row without the PostgREST 1,000-row cap."""
    rows = []
    offset = 0

    while True:
        batch = supabase_request(
            "GET",
            "reviews",
            query={
                "select": "id,review_key,store_name,sv,country,city,author,rating,text,has_text,date,review_date,review_date_source,collected_at",
                "order": "review_date.desc,collected_at.desc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        ) or []

        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    print(f"📦 Supabase 기존 리뷰 전체 로드: {len(rows)}건")
    return rows


def parse_collected_date(value):
    """Return a date from collected_at, falling back to today's KST date."""
    text = normalize_spaces(value)

    if not text:
        return now_kst().date()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return now_kst().date()



STORE_NAME_MIGRATIONS = {
    "Paiks Noodle Mongolia": "Paik's Noodle Sila",
    "Paik's Noodle Mongolia": "Paik's Noodle Sila",
    "Paiks noodle mongolia": "Paik's Noodle Sila",
    "Saemaeul Ulaanbaarar 2": "Saemaeul Seoul St.",
    "Saemaeul Ulaanbaatar 2": "Saemaeul Seoul St.",
    "Saemaeul Mongolia": "Saemaeul Naadam",
    "Saemaeul Ulaanbaatar 1": "Saemaeul Emerald",
    "Saemaeul Emaerald": "Saemaeul Emerald",
}


def migrate_existing_store_names(existing_reviews):
    """Normalize legacy Mongolia store names without losing saved review history."""
    migrated_count = 0

    for review in existing_reviews:
        current_name = normalize_spaces(review.get("store_name", ""))
        new_name = STORE_NAME_MIGRATIONS.get(current_name)

        if new_name and new_name != current_name:
            review["store_name"] = new_name
            migrated_count += 1

    return migrated_count


def migrate_existing_review_dates(existing_reviews):
    """Backfill review_date for legacy reviews using their first collected date."""
    migrated_count = 0
    fallback_count = 0

    for review in existing_reviews:
        if "has_text" not in review:
            review["has_text"] = bool(normalize_spaces(review.get("text", "")))

        if review.get("review_date"):
            continue

        relative_date = review.get("date", "Unknown")
        collected_at = review.get("collected_at", "")
        base_date = parse_collected_date(collected_at)

        review["review_date"] = estimate_review_date(relative_date, base_date)
        review["review_date_source"] = "estimated_from_collected_at"
        migrated_count += 1

        if not collected_at:
            fallback_count += 1

    return migrated_count, fallback_count


def save_migrated_existing_reviews(existing_reviews):
    """Apply legacy normalization in memory before the Supabase upsert."""
    store_name_migrated_count = migrate_existing_store_names(existing_reviews)
    migrated_count, fallback_count = migrate_existing_review_dates(existing_reviews)

    if migrated_count == 0 and store_name_migrated_count == 0:
        print("✅ 기존 리뷰 마이그레이션 불필요")
        return 0

    if store_name_migrated_count > 0:
        print(f"🏪 기존 리뷰 매장명 마이그레이션 준비: {store_name_migrated_count}건")
    if migrated_count > 0:
        print(f"🗓️ 기존 리뷰 날짜 마이그레이션 준비: {migrated_count}건")
    if fallback_count > 0:
        print(f"⚠️ collected_at 없음으로 오늘 날짜를 기준으로 보정: {fallback_count}건")

    return migrated_count + store_name_migrated_count


def make_review_key(review):
    """Canonical dedupe key: author + text + store_name."""
    store_name = normalize_spaces(review.get("store_name", "")).casefold()
    author = normalize_spaces(review.get("author", "Anonymous")).casefold()
    text = normalize_spaces(review.get("text", "")).casefold()

    # Keep the original three-field constitution while normalizing spacing/case.
    return f"{author}|{text}|{store_name}" if store_name else ""



def canonical_review_hash(review):
    return hashlib.sha256(make_review_key(review).encode("utf-8")).hexdigest()


def delete_review_ids(review_ids, batch_size=200):
    for start in range(0, len(review_ids), batch_size):
        batch = review_ids[start:start + batch_size]
        if not batch:
            continue
        supabase_request(
            "DELETE",
            "reviews",
            query={"id": f"in.({','.join(batch)})"},
            prefer="return=minimal",
        )


def patch_review_by_id(review_id, body):
    supabase_request(
        "PATCH",
        "reviews",
        query={"id": f"eq.{review_id}"},
        body=body,
        prefer="return=minimal",
    )


def reconcile_existing_reviews(existing_reviews):
    """Physically dedupe Supabase and restore canonical review_key values."""
    groups = {}
    for review in existing_reviews:
        key = make_review_key(review)
        if key:
            groups.setdefault(key, []).append(review)

    canonical_reviews = []
    duplicate_ids = []
    rekey_count = 0

    for key, group in groups.items():
        canonical_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        keeper = next((r for r in group if r.get("review_key") == canonical_hash), group[0])
        canonical_reviews.append(keeper)

        for row in group:
            if row is not keeper and row.get("id"):
                duplicate_ids.append(str(row["id"]))

        if keeper.get("id") and keeper.get("review_key") != canonical_hash:
            patch_review_by_id(str(keeper["id"]), {"review_key": canonical_hash})
            keeper["review_key"] = canonical_hash
            rekey_count += 1

    if duplicate_ids:
        delete_review_ids(duplicate_ids)

    print("🧹 Supabase 기존 리뷰 정합성 정리 완료")
    print(f"   - 정리 전: {len(existing_reviews)}건")
    print(f"   - 실제 중복 삭제: {len(duplicate_ids)}건")
    print(f"   - canonical review_key 복구: {rekey_count}건")
    print(f"   - 정리 후: {len(canonical_reviews)}건")
    return canonical_reviews

def merge_reviews(existing, new_reviews):
    merged = []
    seen = set()

    for review in new_reviews + existing:
        key = make_review_key(review)

        if not key or key in seen:
            continue

        seen.add(key)
        merged.append(review)

    return merged


def count_new_reviews(existing_reviews, new_reviews):
    existing_keys = set()

    for review in existing_reviews:
        key = make_review_key(review)
        if key:
            existing_keys.add(key)

    new_keys = set()

    for review in new_reviews:
        key = make_review_key(review)
        if key:
            new_keys.add(key)

    return len(new_keys - existing_keys)



def get_existing_keys_for_store(existing_reviews, store_name):
    target_store_name = normalize_spaces(store_name).lower()
    keys = set()

    for review in existing_reviews:
        review_store_name = normalize_spaces(review.get("store_name", "")).lower()

        if review_store_name != target_store_name:
            continue

        key = make_review_key(review)

        if key:
            keys.add(key)

    return keys


def extract_reviews(page, store, existing_keys=None):
    collected = []
    processed_keys = set()
    stalled_count = 0
    last_total = 0
    checked_count = 0
    existing_hit_count = 0

    existing_keys = existing_keys or set()
    recent_only_mode = len(existing_keys) > 0

    if recent_only_mode:
        print(f"⚡ 최근 리뷰 모드 적용: {store['store_name']} / 기존 리뷰 key {len(existing_keys)}개")
        max_rounds = min(MAX_SCROLL_ROUNDS, RECENT_ONLY_MAX_ROUNDS)
    else:
        print(f"📦 기존 리뷰 없음: {store['store_name']} / 초기 수집 모드")
        max_rounds = MAX_SCROLL_ROUNDS

    for round_no in range(max_rounds):
        click_more_buttons(page)
        click_original_review_buttons(page)

        cards, used_selector = get_review_cards(page)
        card_count = cards.count()
        found_this_turn = 0

        print(f"🔎 {round_no + 1}회차 리뷰 카드 감지 수: {card_count} / selector={used_selector}")

        for i in range(card_count):
            try:
                card = cards.nth(i)

                text = get_review_text(card)
                has_text = bool(text and len(text) >= 3)

                noise_words = [
                    "Drag to change",
                    "Collapse side panel",
                    "Expand side panel",
                    "Keyboard shortcuts",
                    "Terms",
                    "Privacy",
                ]

                if has_text and any(word in text for word in noise_words):
                    continue

                relative_date = get_review_date(card)
                author = get_review_author(card)
                rating = get_review_rating(card)

                if not has_text and rating <= 0:
                    continue

                review = {
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "city": store["city"],
                    "author": author,
                    "rating": rating,
                    "text": text if has_text else "",
                    "has_text": has_text,
                    "date": relative_date,
                    "review_date": estimate_review_date(relative_date),
                    "review_date_source": "estimated",
                    "collected_at": now_kst().strftime("%Y-%m-%d"),
                }

                key = make_review_key(review)

                if not key:
                    continue

                if key in processed_keys:
                    continue

                processed_keys.add(key)
                checked_count += 1

                if recent_only_mode and key in existing_keys:
                    existing_hit_count += 1
                    print(
                        f"🟡 기존 리뷰 감지: {existing_hit_count}/{RECENT_ONLY_EXISTING_HIT_LIMIT} "
                        f"/ 확인 {checked_count}/{RECENT_ONLY_MIN_CHECKED}"
                    )

                    if (
                        checked_count >= RECENT_ONLY_MIN_CHECKED
                        and existing_hit_count >= RECENT_ONLY_EXISTING_HIT_LIMIT
                    ):
                        print("✅ 기존 리뷰 충분히 감지. 이 매장 최근 리뷰 확인 종료.")
                        return collected

                    continue

                collected.append(review)
                found_this_turn += 1

                if recent_only_mode and len(collected) >= RECENT_ONLY_MAX_REVIEWS:
                    print(f"✅ 최근 리뷰 신규 후보 상한 도달: {RECENT_ONLY_MAX_REVIEWS}건")
                    return collected

            except Exception as e:
                print(f"⚠️ 개별 리뷰 추출 실패: {e}")
                continue

        if found_this_turn > 0:
            print(f"🔄 {round_no + 1}회차: 신규 후보 {found_this_turn}건 / 이번 매장 누적 {len(collected)}건")
        else:
            print(f"⚠️ {round_no + 1}회차: 신규 후보 없음 / 이번 매장 누적 {len(collected)}건")

        if not recent_only_mode and len(collected) >= MIN_REVIEWS_TARGET:
            print(f"✅ 목표 수집량 도달: {len(collected)}건")
            break

        if len(collected) == last_total:
            stalled_count += 1
        else:
            stalled_count = 0
            last_total = len(collected)

        if stalled_count >= STOP_STALLED_ROUNDS and len(collected) > 0:
            print("✅ 추가 로딩 정체 감지. 빠른 수집 종료.")
            break

        if recent_only_mode and round_no + 1 >= max_rounds:
            print("✅ 최근 리뷰 모드 확인 라운드 완료. 다음 매장으로 이동.")
            break

        scroll_reviews(page)

    return collected


def scrape_store(page, store, existing_reviews=None):
    print(f"\n==============================")
    print(f"🏪 매장 크롤링 시작: {store['store_name']}")
    print(f"👤 담당 SV: {store['sv']} / 국가: {store['country']}")
    print(f"==============================")

    url_candidates = build_url_candidates(store["url"])
    valid_place_detected = False

    for idx, target_url in enumerate(url_candidates):
        print(f"🌐 URL 후보 {idx + 1}/{len(url_candidates)} 진입 시도: {target_url}")

        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"⚠️ 페이지 로딩 중 오류. 계속 진행: {e}")

        page.wait_for_timeout(5000)
        click_cookie_buttons(page)

        print("⏳ Google Maps 기본 페이지 렌더링 대기 중...")
        page.wait_for_timeout(7000)

        if is_valid_google_maps_place_page(page):
            valid_place_detected = True
            print("✅ Google Maps 매장 상세 페이지 확인")

        if not has_review_dom(page):
            open_reviews_panel(page)

        print("⏳ Google Maps 리뷰 패널 렌더링 대기 중...")
        page.wait_for_timeout(4000)

        if wait_for_reviews(page):
            set_reviews_sort_to_newest(page)
            existing_keys = get_existing_keys_for_store(existing_reviews or [], store["store_name"])
            reviews = extract_reviews(page, store, existing_keys)

            if reviews or existing_keys:
                if reviews:
                    print(f"✅ 매장 수집 성공: {store['store_name']} / 신규 후보 {len(reviews)}건")
                else:
                    print(f"✅ 매장 확인 완료: {store['store_name']} / 신규 리뷰 없음")

                return {
                    "ok": True,
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "collected_count": len(reviews),
                    "error": "",
                    "crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
                    "reviews": reviews,
                }

        print(f"⚠️ URL 후보 {idx + 1}에서 리뷰 DOM 감지 실패 또는 리뷰 없음")

    # A real place page with no review DOM is a valid zero-review store, not a crawl failure.
    if valid_place_detected:
        print(f"✅ 리뷰 0건 매장 확인: {store['store_name']} / 정상 성공 처리")
        return {
            "ok": True,
            "store_name": store["store_name"],
            "sv": store["sv"],
            "country": store["country"],
            "collected_count": 0,
            "error": "",
            "crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
            "reviews": [],
        }

    print(f"❌ 매장 수집 실패: {store['store_name']}")
    return {
        "ok": False,
        "store_name": store["store_name"],
        "sv": store["sv"],
        "country": store["country"],
        "collected_count": 0,
        "error": "Google Maps 매장 상세 페이지 또는 리뷰 DOM 감지 실패",
        "crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
        "reviews": [],
    }


def prepare_review_row(review, store_id_map):
    store_name = normalize_spaces(review.get("store_name", ""))
    store_id = store_id_map.get(normalize_store_lookup_key(store_name))

    if not store_id:
        raise RuntimeError(
            f'Supabase stores 테이블에서 매장 ID를 찾지 못했습니다: "{store_name}"'
        )

    row = {
        "review_key": canonical_review_hash(review),
        "store_id": store_id,
        "store_name": store_name,
        "sv": normalize_spaces(review.get("sv", "")),
        "country": normalize_spaces(review.get("country", "")),
        "city": normalize_spaces(review.get("city", "")),
        "author": normalize_spaces(review.get("author", "Anonymous")) or "Anonymous",
        "rating": review.get("rating"),
        "text": review.get("text", ""),
        "has_text": bool(review.get("has_text", normalize_spaces(review.get("text", "")))),
        "date": review.get("date", "Unknown"),
        "review_date": review.get("review_date"),
        "review_date_source": review.get("review_date_source", "estimated"),
        "collected_at": review.get("collected_at") or now_kst().strftime("%Y-%m-%d"),
        "scraped_at": now_kst().isoformat(),
        "source": "google_maps",
    }
    return row


def upsert_review_batch(rows, batch_size=500):
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        supabase_request(
            "POST",
            "reviews",
            query={"on_conflict": "review_key"},
            body=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )


def save_reviews(new_reviews, existing_reviews=None):
    existing_reviews = existing_reviews if existing_reviews is not None else load_existing_reviews()
    existing_keys = {make_review_key(r) for r in existing_reviews if make_review_key(r)}
    unique_new_reviews = merge_reviews([], new_reviews)
    rows_to_insert = [
        review for review in unique_new_reviews
        if make_review_key(review) not in existing_keys
    ]

    store_id_map = load_store_id_map()
    rows = [prepare_review_row(review, store_id_map) for review in rows_to_insert]
    if rows:
        upsert_review_batch(rows)

    print("\n✨ Supabase 저장 완료")
    print(f"   - 기존 리뷰: {len(existing_reviews)}건")
    print(f"   - 이번 수집 후보: {len(new_reviews)}건")
    print(f"   - 수집 내 중복 제외: {len(new_reviews) - len(unique_new_reviews)}건")
    print(f"   - 신규 추가: {len(rows_to_insert)}건")
    print(f"   - 최종 누적: {len(existing_reviews) + len(rows_to_insert)}건")


def save_crawl_status(results, started_at):
    """Append one complete crawl run record for the dashboard."""
    finished_at = now_kst()
    store_rows = [
        {
            "store_name": r["store_name"],
            "sv": r["sv"],
            "country": r["country"],
            "ok": r["ok"],
            "collected_count": r["collected_count"],
            "error": r["error"],
            "crawled_at": r["crawled_at"],
        }
        for r in results
    ]
    failed_stores = [row for row in store_rows if not row["ok"]]
    success_count = len(store_rows) - len(failed_stores)

    run_row = {
        "last_crawled_at": finished_at.strftime("%Y-%m-%d %H:%M:%S"),
        "total_stores": len(store_rows),
        "success_count": success_count,
        "failed_count": len(failed_stores),
        "failed_stores": failed_stores,
        "stores": store_rows,
    }

    supabase_request(
        "POST",
        "crawl_runs",
        body=run_row,
        prefer="return=minimal",
    )

    elapsed_seconds = max(0, int((finished_at - started_at).total_seconds()))
    print("🧾 Supabase crawl_runs 저장 완료")
    print(f"   - 성공: {success_count}/{len(store_rows)}")
    print(f"   - 실패: {len(failed_stores)}건")
    print(f"   - 실행 시간: {elapsed_seconds}초")


def validate_store_configuration(stores, store_id_map):
    """Validate Supabase-driven crawler stores without changing review data."""
    configured_names = []
    configured_urls = []
    missing_store_names = []

    for store in stores:
        store_name = normalize_spaces(store.get("store_name", ""))
        store_url = normalize_spaces(store.get("url", ""))
        sv = normalize_spaces(store.get("sv", ""))
        country = normalize_spaces(store.get("country", ""))

        configured_names.append(normalize_store_lookup_key(store_name))
        configured_urls.append(store_url)

        if not store_name or not store_url or not sv or not country:
            raise RuntimeError(f"필수 매장 설정이 비어 있습니다: {store}")

        if normalize_store_lookup_key(store_name) not in store_id_map:
            missing_store_names.append(store_name)

    duplicate_names = sorted(
        {name for name in configured_names if configured_names.count(name) > 1}
    )
    duplicate_urls = sorted(
        {url for url in configured_urls if url and configured_urls.count(url) > 1}
    )

    if duplicate_names:
        raise RuntimeError(
            "Supabase stores 설정에 중복 매장명이 있습니다: "
            + ", ".join(duplicate_names)
        )

    if duplicate_urls:
        raise RuntimeError(
            "Supabase stores 설정에 중복 Google Maps URL이 있습니다: "
            + ", ".join(duplicate_urls)
        )

    if missing_store_names:
        raise RuntimeError(
            "Supabase stores ID 매핑에 누락된 매장이 있습니다: "
            + ", ".join(missing_store_names)
        )

    print(f"✅ Supabase 매장 설정 검증 완료: {len(stores)}개")


def run_status_only():
    """Check Supabase connectivity and store mapping without opening Google Maps."""
    print("⚡ STATUS_ONLY 모드 시작")
    require_supabase_config()

    stores = load_stores_from_supabase()
    store_id_map = load_store_id_map()
    validate_store_configuration(stores, store_id_map)

    review_probe = supabase_request(
        "GET",
        "reviews",
        query={
            "select": "review_key,store_name,review_date",
            "order": "review_date.desc",
            "limit": "1",
        },
    ) or []

    crawl_probe = supabase_request(
        "GET",
        "crawl_runs",
        query={
            "select": "last_crawled_at,total_stores,success_count,failed_count",
            "order": "last_crawled_at.desc",
            "limit": "1",
        },
    ) or []

    if review_probe:
        latest_review = review_probe[0]
        print(
            "✅ reviews 조회 성공: "
            f"{latest_review.get('store_name', 'Unknown')} / "
            f"{latest_review.get('review_date', 'Unknown')}"
        )
    else:
        print("⚠️ reviews 조회는 성공했지만 저장된 리뷰가 없습니다.")

    if crawl_probe:
        latest_run = crawl_probe[0]
        print(
            "✅ crawl_runs 조회 성공: "
            f"{latest_run.get('success_count', 0)}/"
            f"{latest_run.get('total_stores', 0)} 성공 / "
            f"실패 {latest_run.get('failed_count', 0)}건 / "
            f"{latest_run.get('last_crawled_at', 'Unknown')}"
        )
    else:
        print("⚠️ crawl_runs 조회는 성공했지만 저장된 실행 이력이 없습니다.")

    print("✅ STATUS_ONLY 완료: Google Maps 크롤링 및 reviews 변경 없음")


def run_repair_only():
    print("🧹 REPAIR_ONLY 모드 시작")
    existing_reviews = load_existing_reviews()
    save_migrated_existing_reviews(existing_reviews)
    canonical_reviews = reconcile_existing_reviews(existing_reviews)
    print(f"✅ REPAIR_ONLY 완료: Supabase reviews {len(canonical_reviews)}건 / Google Maps 크롤링 없음")


def scrape():
    if STATUS_ONLY:
        run_status_only()
        return

    if REPAIR_ONLY:
        run_repair_only()
        return

    started_at = now_kst()
    all_new_reviews = []
    crawl_results = []
    stores = load_stores_from_supabase()
    store_id_map = load_store_id_map()
    validate_store_configuration(stores, store_id_map)
    existing_reviews = load_existing_reviews()
    save_migrated_existing_reviews(existing_reviews)
    existing_reviews = reconcile_existing_reviews(existing_reviews)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--lang=en-US,en",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Seoul",
            viewport={"width": 1440, "height": 1000},
        )

        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        )

        page = context.new_page()
        page.set_default_timeout(45000)

        try:
            for store in stores:
                result = scrape_store(page, store, existing_reviews)
                crawl_results.append(result)
                all_new_reviews.extend(result["reviews"])

                page.wait_for_timeout(3000)

            if all_new_reviews or existing_reviews:
                save_reviews(all_new_reviews, existing_reviews)
            else:
                print("❌ 저장할 기존/신규 리뷰가 없습니다.")

            save_crawl_status(crawl_results, started_at)

        except Exception as e:
            print(f"🔥 치명적 오류: {e}")

        finally:
            browser.close()


if __name__ == "__main__":
    scrape()
