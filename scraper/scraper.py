import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")
START_DATE_STR = os.environ.get("START_DATE", "2026-01-01")
START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")

def parse_date(date_str):
    now = datetime.now()
    if not date_str: return now
    match = re.search(r'(\d+)(일|주|달|개월|년)\s*전', date_str)
    if not match: return now
    num, unit = int(match.group(1)), match.group(2)
    if unit == '일': return now - timedelta(days=num)
    elif unit == '주': return now - timedelta(weeks=num)
    elif unit in ['달', '개월']: return now - timedelta(days=num * 30)
    elif unit == '년': return now - timedelta(days=num * 365)
    return now

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            cookies = json.loads(cookies_raw)
            for c in cookies: c['sameSite'] = "Lax"
            context.add_cookies(cookies)

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=60000)
            
            # 1. [리뷰 탭 클릭] - 가장 중요한 단계
            print("🔘 리뷰 탭을 찾는 중...")
            review_tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
            if review_tab.is_visible():
                review_tab.click()
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)
            else:
                print("⚠️ 리뷰 탭을 직접 찾지 못해 현재 화면에서 수집을 시도합니다.")

            reviews = []
            processed_texts = set()
            
            # 2. [스크롤 영역 확보 및 무한 스크롤]
            # 리뷰들이 담긴 스크롤 가능한 컨테이너를 찾습니다.
            scroll_container = page.locator("div[role='main'] >> div.m67qrb").first # 구글 맵 리뷰 컨테이너 클래스
            
            print("⏳ 스크롤 및 수집 시작...")
            for i in range(20):
                # 리뷰 아이템들 탐색
                items = page.locator("div[role='article']").all()
                
                new_found = 0
                for item in items:
                    try:
                        text_el = item.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        text = text_el.inner_text().strip()
                        
                        if not text or text in processed_texts: continue
                        
                        date_el = item.locator(".rsqaWe")
                        date_str = date_el.inner_text() if date_el.count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        if review_date < START_DATE:
                            continue # 특정 날짜 이전이면 건너뛰기 (스크롤은 계속)

                        reviews.append({
                            "author": "고객",
                            "text": text,
                            "date": review_date.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                        new_found += 1
                    except: continue

                print(f"🔄 스크롤 {i+1}회: 새 리뷰 {new_found}건 발견 (총 {len(reviews)}건)")
                
                # 스크롤 내리기: 리뷰 컨테이너 위에서 마우스 휠 조작
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(2000)

            # 3. 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 최종 성공! 총 {len(reviews)}건의 리뷰를 저장했습니다.")

        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
