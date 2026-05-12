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
    START_DATE = datetime.now() - timedelta(days=60)

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
        # 실제 사람처럼 보이기 위해 브라우저 인자를 추가합니다.
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        print(f"🌐 시스템 접속 중...")
        
        try:
            # 접속 시 대기 시간을 넉넉히 줍니다.
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000) 
            
            # [강제 조치] 리뷰 탭이 안 열려있을 경우를 대비해 '리뷰'라는 글자가 보이면 무조건 클릭합니다.
            review_selectors = ["text='리뷰'", "button:has-text('리뷰')", "[aria-label*='리뷰']"]
            for sel in review_selectors:
                try:
                    if page.locator(sel).first.is_visible():
                        page.locator(sel).first.click()
                        print("✅ 리뷰 섹션 진입 성공")
                        page.wait_for_timeout(5000)
                        break
                except: continue
        except Exception as e:
            print(f"⚠️ 초기 접속 지연: {e}")

        reviews = []
        processed_ids = set()
        
        print("⏬ 리뷰 탐색 시작...")
        
        for scroll_count in range(30):
            # 구글 맵의 다양한 리뷰 박스 클래스들을 모두 타겟팅합니다.
            # .jftiEf (일반), .WNo9u (상세), .G5u99 (새 버전)
            items = page.locator(".jftiEf, .WNo9u, .G5u99, [role='article']").all()
            
            if not items:
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2000)
                continue

            for item in items:
                try:
                    # 고유 ID 추출 (중복 방지)
                    r_id = item.get_attribute("data-review-id") or item.inner_text()[:30]
                    if r_id in processed_ids: continue
                    processed_ids.add(r_id)

                    # 더보기 클릭
                    try:
                        more_btn = item.get_by_role("button", name="더보기")
                        if more_btn.count() > 0: more_btn.click(timeout=500)
                    except: pass

                    # 텍스트 추출 (여러 클래스 시도)
                    text = ""
                    text_selectors = [".wiI7pd", ".MyE63c", ".K7RMe"]
                    for ts in text_selectors:
                        target = item.locator(ts)
                        if target.count() > 0:
                            text = target.first.inner_text().strip()
                            break
                    
                    if not text: continue # 내용 없는 리뷰는 패스

                    # 날짜 추출
                    date_str = ""
                    try:
                        date_str = item.locator(".rsqaWe").first.inner_text()
                    except: pass
                    
                    actual_date = parse_relative_date(date_str)
                    if actual_date < START_DATE: continue

                    # 별점 추출
                    rating = 5
                    try:
                        label = item.locator(".kvMYJc").get_attribute("aria-label")
                        rating = int(re.search(r'\d+', label).group())
                    except: pass

                    reviews.append({
                        "author": "고객",
                        "rating": rating,
                        "text": text,
                        "date": actual_date.strftime("%Y-%m-%d")
                    })
                except: continue

            if len(reviews) >= 20: break
            
            # 스크롤 내리기
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2500)

        print(f"✅ 최종 수집 성공: {len(reviews)}건")

        # 저장
        os.makedirs("public/data", exist_ok=True)
        with open("public/data/reviews.json", "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=4)
        
        browser.close()

if __name__ == "__main__":
    scrape_reviews()
