import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

GOOGLE_MAPS_URL = os.environ.get("GOOGLE_MAPS_URL")
# 수집 시작일 설정 (예: 2026-01-01)
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
            page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # 1. [최신순 정렬] 시도
            try:
                # 정렬 버튼 클릭
                sort_btn = page.locator("button[aria-label*='정렬'], button[aria-label*='Sort']").first
                if sort_btn.is_visible():
                    sort_btn.click()
                    page.wait_for_timeout(2000)
                    # '최신순' 혹은 'Newest' 선택
                    page.locator("text='최신순', text='Newest'").first.click()
                    print("✅ 최신순 정렬 완료")
                    page.wait_for_timeout(3000)
            except:
                print("⚠️ 정렬 버튼을 찾지 못했습니다. 기본 순서로 진행합니다.")

            reviews = []
            processed_texts = set()
            
            # 2. [무한 스크롤] 시작
            print("⏳ 리뷰를 불러오는 중 (스크롤 시작)...")
            for i in range(15): # 최대 15번 스크롤 (약 100~150개)
                # 리뷰 아이템들 탐색
                items = page.locator("div[role='article']").all()
                
                stop_scrolling = False
                for item in items:
                    try:
                        # 텍스트 추출
                        text_el = item.locator(".wiI7pd")
                        if text_el.count() == 0: continue
                        text = text_el.inner_text().strip()
                        
                        if text in processed_texts: continue
                        
                        # 날짜 추출 및 검사
                        date_el = item.locator(".rsqaWe")
                        date_str = date_el.inner_text() if date_el.count() > 0 else ""
                        review_date = parse_date(date_str)
                        
                        # 설정한 날짜보다 이전 리뷰가 나오면 중단
                        if review_date < START_DATE:
                            stop_scrolling = True
                            break

                        reviews.append({
                            "author": "고객",
                            "text": text,
                            "date": review_date.strftime("%Y-%m-%d")
                        })
                        processed_texts.add(text)
                    except: continue

                if stop_scrolling: 
                    print(f"🛑 {START_DATE_STR} 이전 리뷰에 도달하여 중단합니다.")
                    break
                
                # 스크롤 내리기 (리뷰 목록 컨테이너 타겟팅)
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2000)
                print(f"🔄 스크롤 중... 현재 {len(reviews)}건 수집")

            # 저장
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
