import os
import json
import time
import re
from playwright.sync_api import sync_playwright

DATA_PATH = "public/data/reviews.json"
STATUS_PATH = "public/data/crawl_status.json"

MAX_SCROLL_ROUNDS = 8
STOP_STALLED_ROUNDS = 2
MIN_REVIEWS_TARGET = 50

STORES = [
    {
        "store_name": "Paik's Noodle Amsterdam",
        "sv": "강소영",
        "country": "Netherlands",
        "city": "Amsterdam",
        "url": "https://www.google.com/maps/place/Paik's+Noodle+Amsterdam/@52.3680585,4.8926513,17z/data=!4m18!1m9!3m8!1s0x47c60978a0095be1:0x5c955b954f65db98!2sPaik's+Noodle+Amsterdam!8m2!3d52.3679846!4d4.8925182!9m1!1b1!16s%2Fg%2F11ldxc_3q5!3m7!1s0x47c60978a0095be1:0x5c955b954f65db98!8m2!3d52.3679846!4d4.8925182!9m1!1b1!16s%2Fg%2F11ldxc_3q5?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D",
    },
    {
        "store_name": "Bornga Wolter Monginsidi",
        "sv": "최성환",
        "country": "Indonesia",
        "city": "Jakarta",
        "url": "https://www.google.com/maps/place/Bornga+Wolter+Monginsidi/@-6.2393833,106.8059313,17z/data=!4m8!3m7!1s0x2e69f16794afe1df:0x3fc1a290a209cef6!8m2!3d-6.2393833!4d106.8085062!9m1!1b1!16s%2Fg%2F1tfd9kxv?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D",
    },
    {
    "store_name": "Saemaeul Thailand",
    "sv": "소도희",
    "country": "Thailand",
    "city": "Bangkok",
    "url": "https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9/@13.7305942,100.397158,11z/data=!4m12!1m2!2m1!1sTHAILAND+SAEMAEUL!3m8!1s0x30e29f07225ca6c7:0x5f5dc0b64eff0693!8m2!3d13.7475043!4d100.5395703!9m1!1b1!15sChFUSEFJTEFORCBTQUVNQUVVTFoTIhF0aGFpbGFuZCBzYWVtYWV1bJIBGmtvcmVhbl9iYXJiZWN1ZV9yZXN0YXVyYW504AEA!16s%2Fg%2F11rghd7fwy?entry=ttu&g_ep=EgoyMDI2MDUwNi4wIKXMDSoASAFQAw%3D%3D",
},
{
    "store_name": "Paik's Noodle Singapore",
    "sv": "이여명",
    "country": "Singapore",
    "city": "Singapore",
    "url": "https://www.google.com/maps/place/Paik's+Noodle/@1.2633826,103.8020909,14z/data=!3m1!5s0x31da19af25771877:0x64dca8531f0ccf88!4m12!1m2!2m1!1sSINGAPORE+PAIKS+NOODLE!3m8!1s0x31da191c85c285cf:0xcf1e805f3426a6f7!8m2!3d1.2948016!4d103.8591949!9m1!1b1!15sChZTSU5HQVBPUkUgUEFJS1MgTk9PRExFWhgiFnNpbmdhcG9yZSBwYWlrcyBub29kbGWSARFrb3JlYW5fcmVzdGF1cmFudJoBJENoZERTVWhOTUc5blMwVkpRMEZuU1VSV2FHRmxkWFZCUlJBQuABAPoBBAgYED0!16s%2Fg%2F11vkfsncfp?entry=ttu&g_ep=EgoyMDI2MDUwNi4wIKXMDSoASAFQAw%3D%3D",
},
]


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
    store_name = normalize_spaces(review.get("store_name", "")).lower()
    author = normalize_spaces(review.get("author", "")).lower()
    text = normalize_spaces(review.get("text", "")).lower()

    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if store_name and author and text:
        return f"{store_name}|{author}|{text}"

    if author and text:
        return f"{author}|{text}"

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


def extract_reviews(page, store):
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

                review = {
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "city": store["city"],
                    "author": get_review_author(card),
                    "rating": get_review_rating(card),
                    "text": text,
                    "date": get_review_date(card),
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
            print(f"🔄 {round_no + 1}회차: {found_this_turn}건 추가 / 이번 매장 누적 {len(collected)}건")
        else:
            print(f"⚠️ {round_no + 1}회차: 신규 리뷰 없음 / 이번 매장 누적 {len(collected)}건")

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


def scrape_store(page, store):
    print(f"\n==============================")
    print(f"🏪 매장 크롤링 시작: {store['store_name']}")
    print(f"👤 담당 SV: {store['sv']} / 국가: {store['country']}")
    print(f"==============================")

    url_candidates = build_url_candidates(store["url"])

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

        if not has_review_dom(page):
            open_reviews_panel(page)

        print("⏳ Google Maps 리뷰 패널 렌더링 대기 중...")
        page.wait_for_timeout(4000)

        if wait_for_reviews(page):
            set_reviews_sort_to_newest(page)
            reviews = extract_reviews(page, store)

            if reviews:
                print(f"✅ 매장 수집 성공: {store['store_name']} / {len(reviews)}건")
                return {
                    "ok": True,
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "collected_count": len(reviews),
                    "error": "",
                    "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "reviews": reviews,
                }

        print(f"⚠️ URL 후보 {idx + 1}에서 리뷰 DOM 감지 실패 또는 리뷰 없음")

    print(f"❌ 매장 수집 실패: {store['store_name']}")
    return {
        "ok": False,
        "store_name": store["store_name"],
        "sv": store["sv"],
        "country": store["country"],
        "collected_count": 0,
        "error": "리뷰 DOM 감지 실패 또는 리뷰 없음",
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reviews": [],
    }


def save_reviews(new_reviews):
    os.makedirs("public/data", exist_ok=True)

    existing_reviews = load_existing_reviews()
    merged_reviews = merge_reviews(existing_reviews, new_reviews)

    new_added_count = count_new_reviews(existing_reviews, new_reviews)
    duplicate_cleaned_count = len(existing_reviews) + len(new_reviews) - len(merged_reviews)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged_reviews, f, ensure_ascii=False, indent=4)

    print(f"\n✨ 저장 완료: {DATA_PATH}")
    print(f"   - 기존 리뷰: {len(existing_reviews)}건")
    print(f"   - 이번 수집: {len(new_reviews)}건")
    print(f"   - 신규 추가: {new_added_count}건")
    print(f"   - 중복 정리: {duplicate_cleaned_count}건")
    print(f"   - 최종 누적: {len(merged_reviews)}건")


def save_crawl_status(results):
    os.makedirs("public/data", exist_ok=True)

    status = {
        "last_crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_stores": len(results),
        "success_count": len([r for r in results if r["ok"]]),
        "failed_count": len([r for r in results if not r["ok"]]),
        "failed_stores": [
            {
                "store_name": r["store_name"],
                "sv": r["sv"],
                "country": r["country"],
                "error": r["error"],
            }
            for r in results
            if not r["ok"]
        ],
        "stores": [
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
        ],
    }

    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=4)

    print(f"🧾 크롤링 상태 저장 완료: {STATUS_PATH}")
    print(f"   - 성공: {status['success_count']}/{status['total_stores']}")
    print(f"   - 실패: {status['failed_count']}건")


def scrape():
    all_new_reviews = []
    crawl_results = []

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
            for store in STORES:
                result = scrape_store(page, store)
                crawl_results.append(result)
                all_new_reviews.extend(result["reviews"])

                page.wait_for_timeout(3000)

            if all_new_reviews:
                save_reviews(all_new_reviews)
            else:
                print("❌ 이번 실행에서 수집된 리뷰가 없습니다.")

            save_crawl_status(crawl_results)

        except Exception as e:
            print(f"🔥 치명적 오류: {e}")

        finally:
            browser.close()


if __name__ == "__main__":
    scrape()
