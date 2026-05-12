import os
import json
import time
import re
import random
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# [1] 설정 로드
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
    if not GOOGLE_MAPS_URL:
        print("❌ URL이 설정되지 않았습니다.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"🌐 매장 접속 시작: {GOOGLE_MAPS_URL}")
        
        # 접속 및 충분한 대기
        page.goto(GOOGLE_MAPS_URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(7000) 

        # 리뷰 탭 강제 진입 시도
        try:
            review_tab = page.get_by_role("button", name=re.compile(r"리뷰", re.I))
            if review_tab.count() > 0:
                review_tab.first.click()
                print("✅ 리뷰 탭 클릭 성공")
                page.wait_for_timeout(5000)
        except:
            print("ℹ️ 리뷰 탭 클릭 건너뜀")

        # 최신순 정렬
        try:
            page.get_by_label("리뷰 정렬").click()
            page.wait_for_timeout(2000)
            page.get_by_role("menuitemradio", name="최신순").click()
            print("✅ 최신순 정렬 완료")
            page.wait_for_timeout(4000)
        except:
            print("⚠️ 정렬 설정 실패 (기본값 사용)")

        reviews = []
        processed_ids = set()
        
        print("⏬ 리뷰 수집 및 스크롤 시작...")
        
        for _ in range(50): # 최대 50회 스크롤
            # 구글 맵의 다양한 리뷰 컨테이너 클래스 대응
            items = page.locator(".jftiEf, .G5u99").all()
            
            if not items:
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(3000)
                continue

            new_found = False
            for item in items:
                r_id = item.get_attribute("data-review-id")
                if not r_id or r_id in processed_ids: continue
                
                processed_ids.add(r_id)
                new_found = True

                try:
                    # 더보기 클릭
                    more = item.locator("button:has-text('더보기')")
                    if more.count() > 0: more.first.click(timeout=1000)
                except: pass

                # 데이터 추출
                author = item.locator(".d4r55, .XE7Yid").first.inner_text() if item.locator(".d4r55, .XE7Yid").count() > 0 else "익명"
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
                    print(f"🛑 날짜 기준 도달 ({actual_date.strftime('%Y-%m-%d')})")
                    new_found = False
                    break

                reviews.append({
                    "author": author,
                    "rating": rating,
                    "text": text,
                    "date": actual_date.strftime("%Y-%m-%d")
                })

            if not new_found and len(reviews) > 0: break
            
            # 스크롤
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(3000)

        print(f"✅ 최종 수집 완료: {len(reviews)}건")

        # 결과 저장
        os.makedirs("public/data", exist_ok=True)
        with open("public/data/reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=4)
        
        browser.close()

if __name__ == "__main__":
    scrape_reviews()
