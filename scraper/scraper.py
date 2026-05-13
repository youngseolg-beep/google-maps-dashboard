import os
import json
import time
import re
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "").strip()

STORE_NAME = "Paik's Noodle Amsterdam"
DATA_PATH = "public/data/reviews.json"


def build_url_candidates(url):
    urls = []

    base = url.strip()
    urls.append(base)

    if "hl=" not in base:
        connector = "&" if "?" in base else "?"
        urls.append(base + connector + "hl=en")

    if "!9m1!1b1" in base:
        reviews_url = base
    else:
        reviews_url = base.split("?")[0].rstrip("/") + "/reviews/"

    urls.append(reviews_url)

    if "hl=" not in reviews_url:
        connector = "&" if "?" in reviews_url else "?"
        urls.append(reviews_url + connector + "hl=en")

    unique = []
    for item in urls:
        if item not in unique:
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
                page.wait_for_timeout(2000)
                return
        except:
            pass


def print_page_diagnostics(page, label):
    print(f"🧪 진단 시작: {label}")

    selectors = [
        "div[role='article']",
        "div[role='feed']",
        ".wiI7pd",
        ".jftiEf",
        ".MyEned",
        ".d4r55",
        ".rsqaof",
        "button",
        "div[aria-label]",
    ]

    for selector in selectors:
        try:
            print(f"   - {selector}: {page.locator(selector).count()}개")
        except:
            print(f"   - {selector}: 확인 실패")

    try:
        buttons = page.locator("button").all()
        print("🧪 버튼 텍스트 샘플:")
        for idx, btn in enumerate(buttons[:40]):
            try:
                txt = btn.inner_text(timeout=1000).strip()
                aria = btn.get_attribute("aria-label", timeout=1000)
                if txt or aria:
                    print(f"   [{idx}] text='{txt}' aria='{aria}'")
            except:
                pass
    except:
        pass


def open_reviews_panel(page):
    print("🔘 리뷰 패널 열기 시도 중...")

    click_targets = [
        ("tab reviews", lambda: page.get_by_role("tab", name=re.compile(r"Reviews|리뷰|Recensies", re.I)).first),
        ("button reviews", lambda: page.get_by_role("button", name=re.compile(r"Reviews|리뷰|Recensies", re.I)).first),
        ("aria reviews", lambda: page.locator("button[aria-label*='Reviews'], button[aria-label*='reviews'], button[aria-label*='리뷰'], button[aria-label*='Recensies'], button[aria-label*='recensies']").first),
        ("jsaction moreReviews", lambda: page.locator("button[jsaction*='pane.rating.moreReviews']").first),
        ("text reviews", lambda: page.locator("text=/Reviews|리뷰|Recensies/i").first),
    ]

    for name, get_locator in click_targets:
        try:
            locator = get_locator()
            if locator.count() > 0:
                print(f"🔘 클릭 후보 발견: {name}")
                locator.click(timeout=5000, force=True)
                page.wait_for_timeout(8000)
                print(f"✅ 클릭 실행 완료: {name}")
                print(f"현재 URL after click: {page.url}")

                if has_review_dom(page):
                    print("✅ 클릭 후 리뷰 DOM 감지")
                    return True
        except Exception as e:
            print(f"⚠️ 클릭 실패: {name} / {e}")

    print("⚠️ 리뷰 패널 클릭으로 열기 실패")
    return False


def has_review_dom(page):
    selectors = [
        "div[role='article']",
        "div[role='feed']",
        ".wiI7pd",
        ".jftiEf",
        ".MyEned",
    ]

    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except:
            pass

    return False


def wait_for_reviews(page):
    selectors = [
        "div[role='article']",
        ".jftiEf",
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
        page.wait_for_timeout(5000)

    return False


def click_more_buttons(page):
    patterns = [
        r"More",
        r"Read more",
        r"자세히 보기",
        r"더보기",
        r"Meer",
        r"Volledige review",
    ]

    for pattern in patterns:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            count = min(buttons.count(), 30)

            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=1000, force=True)
                    page.wait_for_timeout(150)
                except:
                    pass
        except:
            pass


def get_review_cards(page):
    selectors = [
        "div[role='article']",
        ".jftiEf",
        "div[data-review-id]",
    ]

    for selector in selectors:
        try:
            cards = page.locator(selector)
            if cards.count() > 0:
                return cards, selector
        except:
            pass

    return page.locator("div[role='article']"), "div[role='article']"


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
            target.hover(timeout=3000)
        else:
            page.mouse.move(500, 500)
    except:
        page.mouse.move(500, 500)

    page.mouse.wheel(0, 4500)
    page.wait_for_timeout(1000)
    page.keyboard.press("PageDown")
    page.wait_for_timeout(3500)


def extract_reviews(page):
    collected = []
    processed_keys = set()
    stalled_count = 0
    last_total = 0

    for round_no in range(25):
        click_more_buttons(page)

        cards, used_selector = get_review_cards(page)
        card_count = cards.count()
        found_this_turn = 0

        print(f"🔎 {round_no + 1}회차 리뷰 카드 감지 수: {card_count} / selector={used_selector}")

        for i in range(card_count):
            try:
                card = cards.nth(i)

                text = safe_inner_text(card.locator(".wiI7pd"), "")
                if not text:
                    text = safe_inner_text(card.locator(".MyEned"), "")

                text = re.sub(r"\s+", " ", text).strip()

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

                author = safe_inner_text(card.locator(".d4r55"), "Anonymous")
                date_str = safe_inner_text(card.locator(".rsqaof"), "Recent")

                rating_label = safe_attr(
                    card.locator(
                        "span[aria-label*='star'], span[aria-label*='Star'], span[aria-label*='별'], span[aria-label*='ster'], span[aria-label*='Ster']"
                    ),
                    "aria-label",
                    "",
                )

                rating = parse_rating(rating_label)
                key = f"{author}|{date_str}|{text}"

                if key in processed_keys:
                    continue

                collected.append(
                    {
                        "store_name": STORE_NAME,
                        "author": author,
                        "rating": rating,
                        "text": text,
                        "date": date_str,
                        "collected_at": time.strftime("%Y-%m-%d"),
                    }
                )

                processed_keys.add(key)
                found_this_turn += 1

            except Exception as e:
                print(f"⚠️ 개별 리뷰 추출 실패: {e}")
                continue

        if found_this_turn > 0:
            print(f"🔄 {round_no + 1}회차: {found_this_turn}건 추가 / 누적 {len(collected)}건")
        else:
            print(f"⚠️ {round_no + 1}회차: 신규 리뷰 없음 / 누적 {len(collected)}건")

        if len(collected) == last_total:
            stalled_count += 1
        else:
            stalled_count = 0
            last_total = len(collected)

        if stalled_count >= 5 and len(collected) > 0:
            print("✅ 추가 로딩 정체 감지. 수집 종료.")
            break

        scroll_reviews(page)

    return collected


def save_reviews(reviews):
    os.makedirs("public/data", exist_ok=True)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=4)

    print(f"✨ 저장 완료: {DATA_PATH} / {len(reviews)}건")


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
                "--lang=en-US,en",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
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
        page.set_default_timeout(60000)

        try:
            reviews = []

            for idx, target_url in enumerate(url_candidates):
                print(f"🌐 URL 후보 {idx + 1}/{len(url_candidates)} 진입 시도: {target_url}")

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"⚠️ 페이지 로딩 중 오류. 계속 진행: {e}")

                page.wait_for_timeout(5000)
                click_cookie_buttons(page)

                print("⏳ Google Maps 기본 페이지 렌더링 대기 중...")
                page.wait_for_timeout(8000)

                print_page_diagnostics(page, f"URL 후보 {idx + 1} / 클릭 전")

                if not has_review_dom(page):
                    open_reviews_panel(page)

                print("⏳ Google Maps 리뷰 패널 렌더링 대기 중...")
                page.wait_for_timeout(8000)

                print_page_diagnostics(page, f"URL 후보 {idx + 1} / 클릭 후")

                if wait_for_reviews(page):
                    reviews = extract_reviews(page)
                    if reviews:
                        break
                else:
                    print(f"⚠️ URL 후보 {idx + 1}에서 리뷰 DOM 감지 실패")

            if reviews:
                save_reviews(reviews)
                print(f"✅ 성공! 실제 리뷰 {len(reviews)}건 수집 완료.")
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
