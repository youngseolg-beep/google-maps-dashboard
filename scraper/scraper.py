import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "").strip()

STORE_NAME = "Paik's Noodle Amsterdam"
DATA_PATH = "public/data/reviews.json"

MAX_SCROLL_ROUNDS = 10
STOP_STALLED_ROUNDS = 2
MIN_REVIEWS_TARGET = 60


def build_url_candidates(url):
    base = url.strip()
    urls = [base]

    if "!9m1!1b1" not in base:
        reviews_url = base.split("?")[0].rstrip("/") + "/reviews/"
        urls.append(reviews_url)

    unique = []
    for item in urls:
        if item and item not in unique:
            unique.append(item)

    return unique


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


def normalize_spaces(text):
    return re.sub(r"\s+", " ", text or "").strip()


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
        r"Alles accepteren",
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
        "div[role='article']",
        ".jftiEf",
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


def open_reviews_panel(page):
    print("🔘 리뷰 패널 열기 시도 중...")

    click_targets = [
        ("tab reviews", lambda: page.get_by_role("tab", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen", re.I)).first),
        ("button reviews", lambda: page.get_by_role("button", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen", re.I)).first),
        ("aria reviews", lambda: page.locator("button[aria-label*='Reviews'], button[aria-label*='reviews'], button[aria-label*='리뷰'], button[aria-label*='Recensies'], button[aria-label*='recensies'], button[aria-label*='Beoordelingen'], button[aria-label*='beoordelingen']").first),
        ("jsaction moreReviews", lambda: page.locator("button[jsaction*='pane.rating.moreReviews']").first),
        ("text reviews", lambda: page.locator("text=/Reviews|리뷰|Recensies|Beoordelingen/i").first),
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

    for attempt in range(6):
        for selector in selectors:
            try:
                count = page.locator(selector).count()
                if count > 0:
                    print(f"✅ 리뷰 영역 감지: {selector} / {count}개")
                    return True
            except:
                pass

        print(f"⏳ 리뷰 패널 대기 중... {attempt + 1}/6")
        page.wait_for_timeout(3000)

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
        r"Origineel bekijken",
        r"Oorspronkelijke",
        r"Bekijk origineel",
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
    candidates = [
        ".wiI7pd",
        ".MyEned",
    ]

    for selector in candidates:
        text = normalize_spaces(safe_inner_text(card.locator(selector), ""))
        if text:
            return text

    return ""


def get_review_date(card):
    candidates = [
        ".rsqaof",
        "span[class*='rsqaof']",
        "span:has-text('ago')",
        "span:has-text('전')",
        "span:has-text('geleden')",
        "span:has-text('maand')",
        "span:has-text('week')",
        "span:has-text('dag')",
        "span:has-text('jaar')",
        "span:has-text('month')",
        "span:has-text('week')",
        "span:has-text('day')",
        "span:has-text('year')",
    ]

    for selector in candidates:
        try:
            value = normalize_spaces(safe_inner_text(card.locator(selector), ""))
            if value:
                return value
        except:
            pass

    try:
        all_text = card.inner_text(timeout=1000)
        patterns = [
            r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b",
            r"\b\d+\s*(?:초|분|시간|일|주|개월|년)\s*전\b",
            r"\b\d+\s+(?:seconden|minuten|uur|dagen|weken|maanden|jaar)\s+geleden\b",
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
    author = safe_inner_text(card.locator(".d4r55"), "")
    if author:
        return normalize_spaces(author)

    try:
        all_text = card.inner_text(timeout=1000).splitlines()
        for line in all_text:
            line = normalize_spaces(line)
            if line and len(line) <= 60:
                if not re.search(r"star|별|ago|전|geleden|review|리뷰|recensie", line, re.I):
                    return line
    except:
        pass

    return "Anonymous"


def get_review_rating(card):
    rating_label = safe_attr(
        card.locator(
            "span[aria-label*='star'], span[aria-label*='Star'], span[aria-label*='stars'], span[aria-label*='Stars'], span[aria-label*='별'], span[aria-label*='ster'], span[aria-label*='Ster']"
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


def load_existing_reviews():
    if not os.path.exists(DATA_PATH):
        return []

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            print(f"📦 기존 리뷰 로드: {len(data)}건")
            return data
    except Exception as e:
        print(f"⚠️ 기존 JSON 로드 실패. 새로 저장 진행: {e}")

    return []


def make_review_key(review):
    author = normalize_spaces(review.get("author", ""))
    text = normalize_spaces(review.get("text", ""))
    date = normalize_spaces(review.get("date", ""))

    if author and text and date:
        return f"{author}|{date}|{text}"

    return text


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


def extract_reviews(page):
    collected = []
    processed_keys = set()
    stalled_count = 0
    last_total = 0

    for round_no in range(MAX_SCROLL_ROUNDS):
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

                if not text or len(text) < 3:
                    continue

                noise_words = [
                    "Drag to change",
                    "Collapse side panel",
                    "Expand side panel",
                    "Keyboard shortcuts",
                    "Terms",
                    "Privacy",
                ]

                if any(word in text for word in noise_words):
                    continue

                author = get_review_author(card)
                date_str = get_review_date(card)
                rating = get_review_rating(card)

                review = {
                    "store_name": STORE_NAME,
                    "author": author,
                    "rating": rating,
                    "text": text,
                    "date": date_str,
                    "collected_at": time.strftime("%Y-%m-%d"),
                }

                key = make_review_key(review)

                if key in processed_keys:
                    continue

                collected.append(review)
                processed_keys.add(key)
                found_this_turn += 1

            except Exception as e:
                print(f"⚠️ 개별 리뷰 추출 실패: {e}")
                continue

        if found_this_turn > 0:
            print(f"🔄 {round_no + 1}회차: {found_this_turn}건 추가 / 이번 실행 누적 {len(collected)}건")
        else:
            print(f"⚠️ {round_no + 1}회차: 신규 리뷰 없음 / 이번 실행 누적 {len(collected)}건")

        if len(collected) >= MIN_REVIEWS_TARGET:
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

        scroll_reviews(page)

    return collected


def save_reviews(new_reviews):
    os.makedirs("public/data", exist_ok=True)

    existing_reviews = load_existing_reviews()
    merged_reviews = merge_reviews(existing_reviews, new_reviews)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged_reviews, f, ensure_ascii=False, indent=4)

    added_count = len(merged_reviews) - len(existing_reviews)

    print(f"✨ 저장 완료: {DATA_PATH}")
    print(f"   - 기존 리뷰: {len(existing_reviews)}건")
    print(f"   - 이번 수집: {len(new_reviews)}건")
    print(f"   - 신규 추가: {added_count}건")
    print(f"   - 최종 누적: {len(merged_reviews)}건")


def scrape():
    if not GOOGLE_MAPS_URL:
        print("❌ GOOGLE_MAPS_URL 환경변수가 비어 있습니다.")
        return

    url_candidates = build_url_candidates(GOOGLE_MAPS_URL)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--lang=nl-NL,nl,en-US,en",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="nl-NL",
            timezone_id="Europe/Amsterdam",
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
            reviews = []

            for idx, target_url in enumerate(url_candidates):
                print(f"🌐 URL 후보 {idx + 1}/{len(url_candidates)} 진입 시도: {target_url}")

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    print(f"⚠️ 페이지 로딩 중 오류. 계속 진행: {e}")

                page.wait_for_timeout(4000)
                click_cookie_buttons(page)

                print("⏳ Google Maps 기본 페이지 렌더링 대기 중...")
                page.wait_for_timeout(5000)

                if not has_review_dom(page):
                    open_reviews_panel(page)

                print("⏳ Google Maps 리뷰 패널 렌더링 대기 중...")
                page.wait_for_timeout(4000)

                if wait_for_reviews(page):
                    reviews = extract_reviews(page)
                    if reviews:
                        break
                else:
                    print(f"⚠️ URL 후보 {idx + 1}에서 리뷰 DOM 감지 실패")

            if reviews:
                save_reviews(reviews)
                print(f"✅ 성공! 이번 실행 리뷰 {len(reviews)}건 수집 완료.")
            else:
                print("❌ 데이터가 발견되지 않았습니다.")
                print(f"현재 URL: {page.url}")
                print(f"페이지 제목: {page.title()}")

        except Exception as e:
            print(f"🔥 치명적 오류: {e}")

        finally:
            browser.close()


if __name__ == "__main__":
    scrape()
