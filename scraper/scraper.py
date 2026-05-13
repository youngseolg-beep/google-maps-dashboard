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
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )

        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                for c in cookies: c['sameSite'] = "Lax"
                context.add_cookies(cookies)
                print("🍪 신분증(쿠키) 장착 완료")
            except: pass

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            print("⏳ 페이지 안정화 대기 중...")
            page.wait_for_timeout(10000)
            
            # 1. 리뷰 탭 클릭
            review_tab = page.locator("button[role='tab']:has-text('리뷰'), button[role='tab']:has-text('Reviews')").first
            if review_tab.is_visible():
                review_tab.click()
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)

            reviews = []
            processed_texts = set()
            
            # 2. 스크롤 및 수집
            print("⏳ 무한 스크롤 모드 가동...")
            
            for i in range(20):
                # 현재 로드된 리뷰들 수집
                items = page.locator(".wiI7pd").all()
                for item in items:
                    try:
                        text = item.inner_text().strip()
                        if not text or text in processed_texts: continue
                        
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        date_str = parent.locator(".rsqaWe").first.inner_text() if parent.locator(".rsqaWe").count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        if review_date < START_DATE: continue

                        reviews.append({"author": "고객", "text": text, "date": review_date.strftime("%Y-%m-%d")})
                        processed_texts.add(text)
                    except: continue

                print(f"🔄 회차 {i+1}: 누적 {len(reviews)}건")

                # [강력 수정] 리뷰 리스트가 들어있는 컨테이너를 찾아 강제로 바닥까지 스크롤
                page.evaluate("""
                    const scrollable = document.querySelector('div[role="main"] div.m67qrb') || 
                                     document.querySelector('.DxyBCb') || 
                                     document.querySelector('.m67qrb');
                    if (scrollable) {
                        scrollable.scrollTop = scrollable.scrollHeight;
                    } else {
                        window.scrollBy(0, 2000);
                    }
                """)
                
                # 구글 서버가 데이터를 줄 시간을 줌 (속도를 조금 늦추는 게 안전함)
                page.wait_for_timeout(4000)

            # 3. 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 최종 성공! 총 {len(reviews)}건 저장.")

        except Exception as e:
            print(f"❌ 에러: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
