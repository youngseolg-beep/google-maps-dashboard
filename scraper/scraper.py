import os
import json
import time
import random
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# 환경 변수에서 설정 가져오기
GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "http://googleusercontent.com/maps.google.com/6")
START_DATE_STR = os.environ.get("START_DATE", "2026-01-01")

def parse_relative_date(date_str):
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
        # [변장 1] 자동화 감지 우회 옵션
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()

        print(f"🚀 자동 수집 시작: {GOOGLE_MAPS_URL}")
        
        try:
            page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(random.randint(5000, 8000)) # 랜덤 대기

            # [핵심] 리뷰 탭 찾기 및 클릭
            # 구글은 로봇이 접속하면 화면 구조를 살짝 바꿉니다. 여러 이름을 다 뒤집니다.
            review_selectors = ["text='리뷰'", "text='Reviews'", "[aria-label*='리뷰']", ".hh7dbf"]
            for selector in review_selectors:
                try:
                    if page.locator(selector).first.is_visible():
                        page.locator(selector).first.click()
                        print(f"✅ 리뷰 탭 클릭 성공 ({selector})")
                        page.wait_for_timeout(3000)
                        break
                except: continue

            reviews = []
            processed_ids = set()

            # 스크롤 및 수집 (최대 10번)
            for i in range(10):
                # 로컬에서 성공했던 그 이름표(클래스)들 총동원
                items = page.locator(".wiI7pd, .MyE63c, .K7RMe").all()
                for item in items:
                    try:
                        text = item.inner_text().strip()
                        if not text or text in processed_ids: continue
                        
                        parent = item.locator("xpath=./ancestor::div[contains(@role, 'article')]")
                        date_str = ""
                        if parent.count() > 0:
                            date_el = parent.first.locator(".rsqaWe")
                            if date_el.count() > 0:
                                date_str = date_el.first.inner_text()
                        
                        reviews.append({
                            "author": "고객",
                            "rating": 5,
                            "text": text,
                            "date": parse_relative_date(date_str).strftime("%Y-%m-%d")
                        })
                        processed_ids.add(text)
                    except: continue

                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(random.randint(2000, 4000))
                print(f"🔄 스크롤 {i+1}회 진행 중... (현재 {len(reviews)}건)")

            # 데이터 저장
            os.makedirs("public/data", exist_ok=True)
            with open("public/data/reviews.json", "w", encoding="utf-8") as f:
                json.dump(reviews, f, ensure_ascii=False, indent=4)
            
            print(f"🏁 수집 완료: 총 {len(reviews)}건")

        except Exception as e:
            print(f"❌ 에러 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape()
