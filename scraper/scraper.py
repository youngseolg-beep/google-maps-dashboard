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
        # 자동화 감지 우회 설정 강화
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

        cookies_raw = os.environ.get("GOOGLE_COOKIES")
        if cookies_raw:
            try:
                cookies = json.loads(cookies_raw)
                for c in cookies: c['sameSite'] = "Lax"
                context.add_cookies(cookies)
                print("🍪 신분증 장착 완료")
            except: pass

        page = context.new_page()
        
        try:
            print(f"🌐 접속 중: {GOOGLE_MAPS_URL}")
            # [핵심] networkidle 대신 domcontentloaded 사용 (타임아웃 방지)
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 페이지가 안정화될 때까지 10초간 '깡'으로 기다립니다.
            print("⏳ 페이지 안정화 기다리는 중...")
            page.wait_for_timeout(10000)
            
            # 1. 리뷰 탭 클릭 시도 (여러 패턴 대응)
            print("🔘 리뷰 탭 클릭 시도...")
            review_selectors = [
                "button[role='tab']:has-text('리뷰')",
                "button[role='tab']:has-text('Reviews')",
                "text='리뷰'",
                ".hh7dbf"
            ]
            
            for selector in review_selectors:
                try:
                    target = page.locator(selector).first
                    if target.is_visible():
                        target.click()
                        print(f"✅ 리뷰 탭 클릭 성공 ({selector})")
                        page.wait_for_timeout(5000)
                        break
                except: continue

            reviews = []
            processed_texts = set()
            
            # 2. 스크롤 및 수집
            print("⏳ 스크롤 및 수집 시작...")
            for i in range(15):
                items = page.locator(".wiI7pd, .MyE63c").all()
                new_found = 0
                
                for item in items:
                    try:
                        text = item.inner_text().strip()
                        if not text or text in processed_texts: continue
                        
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        date_str = parent.locator(".rsqaWe").first.inner_text() if parent.locator(".rsqaWe").count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        if review_date < START_DATE: continue

                        reviews.append({
                            "author": "고객",
                            "text": text,
                            "date": review_date.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                        new_found += 1
                    except: continue

                print(f"🔄 스크롤 {i+1}회: 총 {len(reviews)}건 확보")
                
                # 화면 중앙 지점에서 스크롤 (더 안정적임)
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2000)

            # 3. 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"✨ 수집 성공! 총 {len(reviews)}건 저장 완료.")

        except Exception as e:
            print(f"❌ 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
