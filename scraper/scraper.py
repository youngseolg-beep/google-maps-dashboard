import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL", "")
START_DATE_STR = os.environ.get("START_DATE", "2026-05-01")

try:
    START_DATE = datetime.strptime(START_DATE_STR, "%Y-%m-%d")
except:
    START_DATE = datetime.now() - timedelta(days=30)

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

def scrape_reviews():
    if not GOOGLE_MAPS_URL: return

    with sync_playwright() as p:
        # [수정] 브라우저 설정을 더 가볍게 잡습니다.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        
        print(f"🌐 매장 접속 시도...")
        
        # [핵심 변경] 완벽한 로딩을 기다리지 않고 접속 즉시(commit) 진행합니다.
        try:
            page.goto(GOOGLE_MAPS_URL, wait_until="commit", timeout=60000)
            print("✅ 접속 확인, 로딩 대기 중...")
            page.wait_for_timeout(10000) # 딱 10초만 눈 감고 기다려줍니다.
        except Exception as e:
            print(f"⚠️ 접속 지연 발생했으나 계속 진행합니다.")

        # 리뷰 버튼 찾기 (주소에 이미 /reviews 가 포함된 경우를 대비)
        try:
            # '리뷰' 글자가 포함된 버튼을 찾아 클릭
            page.get_by_role("button", name=re.compile(r"리뷰", re.I)).first.click(timeout=5000)
            page.wait_for_timeout(3000)
        except:
            pass

        reviews = []
        processed_ids = set()
        
        print("⏬ 데이터 수집 시작...")
        
        # 스크롤 횟수를 줄이고 핵심만 긁습니다.
        for _ in range(20): 
            items = page.locator(".jftiEf").all()
            if not items:
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2000)
                continue

            for item in items:
                r_id = item.get_attribute("data-review-id")
                if not r_id or r_id in processed_ids: continue
                processed_ids.add(r_id)

                try:
                    # 더보기 클릭 (있을 때만)
                    item.locator("button:has-text('더보기')").click(timeout=500)
                except: pass

                author = item.locator(".d4r55").first.inner_text() if item.locator(".d4r55").count() > 0 else "익명"
                text = item.locator(".wiI7pd").first.inner_text() if item.locator(".wiI7pd").count() > 0 else ""
                
                rating_el = item.locator(".kvMYJc")
                rating = 0
                if rating_el.count() > 0:
                    label = rating_el.get_attribute("aria-label") or ""
                    match = re.search(r'\d+', label)
                    if match: rating = int(match.group())

                date_str = item.locator(".rsqaWe").first.inner_text() if item.locator(".rsqaWe").count() > 0 else ""
                actual_date = parse_relative_date(date_str)

                if actual_date < START_DATE:
                    print(f"🛑 날짜 기준 도달")
                    break

                reviews.append({"author": author, "rating": rating, "text": text, "date": actual_date.strftime("%Y-%m-%d")})

            if len(reviews) > 30: break # 테스트를 위해 일단 30개만 모이면 종료
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2000)

        print(f"✅ 수집 완료: {len(reviews)}건")
        os.makedirs("public/data", exist_ok=True)
        with open("public/data/reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=4)
        browser.close()

if __name__ == "__main__":
    scrape_reviews()
